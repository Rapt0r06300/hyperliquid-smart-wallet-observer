"""[PORTABILITE items 20 & 22] Construction d'une archive PORTABLE de HyperSmart, avec re-verification.

But (critere final de Flo) : apres extraction de cette archive sur un AUTRE PC Windows x64
compatible, double-clic `LANCER_HYPERSMART.cmd` -> recolte -> cloture -> double-clic
`ANALYSER_BACKTESTS_REPLAYS.cmd`, SANS modifier aucun chemin ni installer Python/deps a la main.

`CREER_ARCHIVE_PORTABLE.cmd` appelle ce module. Il, automatiquement (item 20) :
  1. exige la PREUVE que tous les writers sont arretes (reutilise session_harvest, FAIL-CLOSED) ;
  2. REFUSE de construire s'il reste une session ACTIVE (jamais une demi-session dans l'archive) ;
  3. checkpoint/TRUNCATE le WAL de chaque SQLite puis relache les fichiers -wal/-shm transitoires ;
  4. exclut PID, verrous, marqueurs machine, temporaires, .git, venv, bundles ;
  5. conserve toutes les sessions COMPLETE/QUARANTINED choisies (historique, PnL) ;
  6. neutralise tout chemin absolu de build dans les metadonnees (sinon REFUS) ;
  7. calcule un manifeste SHA-256 complet (item 22) embarque dans l'archive ;
  8. cree une archive versionnee ;
  9. RE-VERIFIE l'archive apres coup (chaque membre re-hashe == manifeste).

Tout est en stdlib (zipfile/sqlite3/hashlib) : constructible et testable hors Windows, 0 reseau,
0 dependance a git/python systeme (le SHA git est LU dans .git, jamais via un `git` du PATH).
"""
from __future__ import annotations

import io
import json
import os
import platform
import re
import sqlite3
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Iterable

from hl_observer.ops import session_catalog as SC
from hl_observer.ops.registre_pids import REGISTRE_RELPATH

SCHEMA_MANIFESTE = "hypersmart.portable_manifest.v1"
NOM_MANIFESTE = "PORTABLE_MANIFEST.json"

# item 20.4 — jamais dans une archive portable : identite machine, verrous, temporaires, VCS, venv.
DOSSIERS_EXCLUS = ("__pycache__", ".git", ".venv", "venv", "env", "node_modules",
                   ".pytest_cache", ".mypy_cache", ".ruff_cache", "portable_runtime",
                   ".venv-portable", "tmp_pytest", "htmlcov")
SUFFIXES_EXCLUS = (".pyc", ".pyo", ".log", ".lock", ".pid", ".tmp", ".bundle",
                   ".sqlite3-wal", ".sqlite3-shm", ".sqlite-wal", ".sqlite-shm",
                   "-wal", "-shm", ".db-wal", ".db-shm")
# item 21 « aucune cle copiee » : matiere de cle exclue par EXTENSION (jamais par sous-chaine, qui
# ferait tomber du code source legitime comme private_helpers.py). Defense en profondeur : meme si le
# projet est paper-strict (0 cle reelle), une archive ne doit JAMAIS transporter de secret.
SUFFIXES_SECRETS = (".key", ".pem", ".p12", ".pfx", ".mnemonic", ".seed", ".keystore")
FICHIERS_EXCLUS = (REGISTRE_RELPATH.as_posix(),                     # registre PID du lanceur
                   "runtime/data/lanceur_session_marqueur.txt",     # marqueur anti-orphelin (machine)
                   "runtime/data/COURANTE.json",                    # pointeur de session vivante
                   ".analyse.lock", NOM_MANIFESTE)
# item 20.6 — un chemin absolu machine-specifique ne doit jamais survivre dans les metadonnees.
_ABSOLU = re.compile(r"(?:[A-Za-z]:\\|\\\\[^\s\"]+|/(?:home|Users)/)")


# ── PREUVE + SESSIONS ───────────────────────────────────────────────────────────────────────
# `preuve_writers_arretes` est FAIL-CLOSED pour la CLOTURE (registre absent = arret non prouve, on ne
# marque jamais COMPLETE dans le doute). Pour l'ARCHIVE, la question est differente : « quelque chose
# ecrit-il MAINTENANT ? ». Un registre ABSENT/ vide n'est pas un writer vivant — c'est l'etat normal
# quand le lanceur ne tourne pas ; le garde-fou d'integrite est alors « aucune session ACTIVE » (item
# 20.2). On distingue donc les VRAIS writers vivants des simples marqueurs d'absence de registre.
_MARQUEURS_REGISTRE = frozenset({"REGISTRE_ABSENT", "REGISTRE_ILLISIBLE", "REGISTRE_INCOMPLET",
                                 "REGISTRE_CORROMPU"})


def preuve_arret(root: str | Path, *, pid_vivant=None) -> tuple[bool, list[str]]:
    """item 20.1 : reutilise la preuve FAIL-CLOSED du harvest (jamais une re-implementation)."""
    from hl_observer.ops.session_harvest import preuve_writers_arretes, _pid_vivant_reel
    return preuve_writers_arretes(root, pid_vivant=pid_vivant or _pid_vivant_reel)


def writers_vivants(root: str | Path, *, pid_vivant=None) -> list[str]:
    """VRAIS processus ecrivains encore vivants (hors marqueurs d'absence de registre). Une liste non
    vide = quelque chose ecrit -> l'archive doit etre refusee (item 20.1)."""
    _arretes, motifs = preuve_arret(root, pid_vivant=pid_vivant)
    return [m for m in motifs if m not in _MARQUEURS_REGISTRE]


def sessions_actives(root: str | Path) -> list[str]:
    """item 20.2 : run_id des sessions encore ACTIVE (elles interdisent la construction)."""
    return [s["run_id"] for s in SC.scanner_sessions(root) if s.get("statut") == SC.STATUT_ACTIVE]


def sessions_actives(root: str | Path) -> list[str]:
    """item 20.2 : run_id des sessions encore ACTIVE (elles interdisent la construction)."""
    return [s["run_id"] for s in SC.scanner_sessions(root) if s.get("statut") == SC.STATUT_ACTIVE]


# ── SQLITE WAL (item 20.3) ───────────────────────────────────────────────────────────────────
def checkpoint_wal_sqlite(chemin: str | Path) -> dict:
    """TRUNCATE le WAL d'une base puis repasse en journal DELETE : la base devient auto-portante,
    les sidecars -wal/-shm disparaissent (et sont de toute facon exclus). Rend un petit verdict."""
    chemin = Path(chemin)
    try:
        con = sqlite3.connect(str(chemin))
        try:
            con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            con.execute("PRAGMA journal_mode=DELETE")
            con.commit()
        finally:
            con.close()
        return {"base": chemin.name, "ok": True}
    except sqlite3.Error as exc:                       # base verrouillee/corrompue = on le DIT
        return {"base": chemin.name, "ok": False, "erreur": str(exc)}


def preparer_sqlite(root: str | Path) -> list[dict]:
    root = Path(root)
    out: list[dict] = []
    for ext in ("*.sqlite", "*.sqlite3", "*.db"):
        for p in root.rglob(ext):
            if any(part in DOSSIERS_EXCLUS for part in p.relative_to(root).parts):
                continue
            out.append(checkpoint_wal_sqlite(p))
    return out


# ── SELECTION DES FICHIERS (items 20.4/20.5) ─────────────────────────────────────────────────
def est_exclu(rel: str) -> bool:
    rel_posix = Path(rel).as_posix()
    parts = Path(rel).parts
    if any(part in DOSSIERS_EXCLUS for part in parts):
        return True
    if rel_posix in FICHIERS_EXCLUS or Path(rel).name in FICHIERS_EXCLUS:
        return True
    low = rel_posix.lower()
    if any(low.endswith(sfx) for sfx in SUFFIXES_EXCLUS):
        return True
    if any(low.endswith(sfx) for sfx in SUFFIXES_SECRETS):          # item 21 : jamais de cle dans l'archive
        return True
    nom = Path(rel).name.lower()
    if nom == ".env" or nom.startswith(".env."):                    # secrets d'environnement
        return True
    return False


def lister_pour_archive(root: str | Path) -> tuple[list[str], list[str]]:
    """(inclus, exclus) en chemins POSIX relatifs, tries. Les sessions COMPLETE/QUARANTINED sont
    conservees (item 20.5) ; seuls PID/verrous/temporaires/machine tombent (item 20.4)."""
    root = Path(root)
    inclus, exclus = [], []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        (exclus if est_exclu(rel) else inclus).append(rel)
    return inclus, sorted(exclus)


# ── METADONNEES (item 20.6) ──────────────────────────────────────────────────────────────────
def neutraliser_metadonnees(texte: str, racine: str | Path) -> tuple[str, int]:
    """Retire le prefixe racine de build des metadonnees (chemins -> relatifs). Rend (texte, nb)."""
    racine_txt = str(Path(racine))
    variantes = {racine_txt, racine_txt.replace("\\", "/"),
                 racine_txt.replace("\\", "\\\\"), str(Path(racine).as_posix())}
    n = 0
    for v in sorted(variantes, key=len, reverse=True):
        if v and v in texte:
            n += texte.count(v)
            texte = texte.replace(v + os.sep, "").replace(v + "/", "").replace(v + "\\\\", "")
            texte = texte.replace(v, ".")
    return texte, n


def chemins_absolus_residuels(texte: str) -> list[str]:
    """item 20.6 : tout chemin absolu machine-specifique encore present (apres neutralisation)."""
    return sorted({m.group(0) for m in _ABSOLU.finditer(texte)})


# ── MANIFESTE (item 22) ──────────────────────────────────────────────────────────────────────
def _git_sha_depuis_dossier(root: str | Path) -> str:
    """SHA git LU dans .git (jamais via un `git` du PATH : item 16 interdit le git systeme)."""
    g = Path(root) / ".git"
    try:
        head = (g / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref:"):
            ref = head.split(":", 1)[1].strip()
            p = g / ref
            if p.is_file():
                return p.read_text(encoding="utf-8").strip()
            paquet = g / "packed-refs"
            if paquet.is_file():
                for ln in paquet.read_text(encoding="utf-8").splitlines():
                    if ln.strip().endswith(" " + ref):
                        return ln.split(" ", 1)[0].strip()
            return ""
        return head                                    # HEAD detache = SHA brut
    except OSError:
        return ""


def _categorie_binaire(rel: str) -> str | None:
    low = rel.lower()
    if low.endswith(".whl"):
        return "wheel"
    if low.endswith((".dll", ".pyd")):
        return "dll"
    if low.endswith(".exe"):
        return "exe"
    return None


def construire_manifeste(root: str | Path, inclus: Iterable[str], exclus: Iterable[str], *,
                         version: str = "", git_sha: str | None = None,
                         horloge=time.time) -> dict:
    """item 22 : version+SHA git, python, os/arch, hashes exe/DLL/wheels + tous fichiers requis,
    donnees incluses/exclues, date de build, commande de verification, empreinte globale."""
    root = Path(root)
    fichiers: dict[str, dict] = {}
    binaires: dict[str, dict] = {}
    for rel in sorted(inclus):
        sha, taille = SC.sha256_fichier(root / rel)
        fichiers[rel] = {"sha256": sha, "taille": taille}
        cat = _categorie_binaire(rel)
        if cat:
            binaires[rel] = {"categorie": cat, "sha256": sha, "taille": taille}
    empreinte = _empreinte_manifeste(fichiers)
    sessions = [s["run_id"] for s in SC.scanner_sessions(root)
                if s.get("statut") in (SC.STATUT_COMPLETE, SC.STATUT_QUARANTINED)]
    ts = int(horloge() * 1000)
    return {
        "schema": SCHEMA_MANIFESTE,
        "hypersmart_version": version or _version_projet(root),
        "git_sha": (git_sha if git_sha is not None else _git_sha_depuis_dossier(root)),
        "python": {"version": platform.python_version(),
                   "implementation": platform.python_implementation()},
        "plateforme": {"os": platform.system(), "arch": platform.machine(),
                       "cible": "Windows-x64"},
        "date_build_ms": ts,
        "nombre_fichiers": len(fichiers),
        "empreinte_globale": empreinte,
        "binaires": binaires,
        "deps": _deps_verrouillees(root),
        "donnees_incluses": sessions,
        "donnees_exclues": sorted(set(list(DOSSIERS_EXCLUS) + list(SUFFIXES_EXCLUS)
                                       + list(FICHIERS_EXCLUS))),
        "commande_verification": "CREER_ARCHIVE_PORTABLE.cmd --verifier <archive.zip>",
        "fichiers": fichiers,
    }


def _empreinte_manifeste(fichiers: dict[str, dict]) -> str:
    import hashlib
    h = hashlib.sha256()
    for rel in sorted(fichiers):
        h.update(rel.encode("utf-8"))
        h.update(str(fichiers[rel].get("sha256", "")).encode("utf-8"))
    return h.hexdigest()


def _version_projet(root: Path) -> str:
    for nom in ("VERSION", "VERSION.txt"):
        p = root / nom
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8").strip() or "0.0.0-dev"
            except OSError:
                pass
    return "0.0.0-dev"


def _deps_verrouillees(root: Path) -> list[str]:
    for nom in ("requirements.lock", "requirements-portable.txt", "requirements.txt"):
        p = root / nom
        if p.is_file():
            try:
                return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
                        if ln.strip() and not ln.strip().startswith("#")]
            except OSError:
                pass
    return []


# ── ECRITURE + RE-VERIFICATION (items 20.8/20.9) ─────────────────────────────────────────────
class ArchiveRefuseeError(RuntimeError):
    """Refus explicite (writers vivants, session ACTIVE, chemin absolu residuel...)."""


def _est_metadonnee(rel: str) -> bool:
    low = rel.lower()
    return low.endswith(".json") or low.endswith(".txt") or low.endswith(".cfg") \
        or low.endswith(".ini") or low.endswith(".toml")


def ecrire_archive(root: str | Path, cible: str | Path, inclus: Iterable[str],
                   manifeste: dict) -> dict:
    """Ecrit l'archive .zip. Les metadonnees texte sont neutralisees (chemins absolus -> relatifs) ;
    un chemin absolu RESIDUEL fait ECHOUER (item 20.6). Le manifeste est embarque a la racine."""
    root, cible = Path(root), Path(cible)
    cible.parent.mkdir(parents=True, exist_ok=True)
    inclus = sorted(inclus)
    neutralises, residus = 0, {}
    with zipfile.ZipFile(cible, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for rel in inclus:
            src = root / rel
            if _est_metadonnee(rel):
                try:
                    txt = src.read_text(encoding="utf-8")
                    txt2, n = neutraliser_metadonnees(txt, root)
                    neutralises += n
                    abs_res = chemins_absolus_residuels(txt2)
                    if abs_res:
                        residus[rel] = abs_res
                    z.writestr(rel, txt2)
                    continue
                except (OSError, UnicodeDecodeError):
                    pass                               # binaire deguise : on ecrit brut
            z.write(src, rel)
        z.writestr(NOM_MANIFESTE, json.dumps(manifeste, ensure_ascii=False, indent=2, sort_keys=True))
    if residus:
        cible.unlink(missing_ok=True)
        raise ArchiveRefuseeError("chemins absolus residuels dans %d metadonnee(s): %s"
                                  % (len(residus), json.dumps(residus, ensure_ascii=False)))
    return {"archive": str(cible), "membres": len(inclus) + 1, "chemins_neutralises": neutralises}


def reverifier_archive(cible: str | Path) -> dict:
    """item 20.9 : re-ouvre l'archive, re-hashe CHAQUE membre, compare au manifeste embarque.
    Rend {ok, verifies, divergences[], manquants[]}. Aucune confiance aveugle dans l'ecriture."""
    cible = Path(cible)
    with zipfile.ZipFile(cible, "r") as z:
        try:
            manifeste = json.loads(z.read(NOM_MANIFESTE).decode("utf-8"))
        except KeyError:
            return {"ok": False, "raison": "MANIFESTE_ABSENT"}
        attendus = manifeste.get("fichiers", {})
        noms = set(z.namelist()) - {NOM_MANIFESTE}
        divergences, manquants, verifies = [], [], 0
        for rel, meta in attendus.items():
            if rel not in noms:
                manquants.append(rel)
                continue
            data = z.read(rel)
            import hashlib
            sha = hashlib.sha256(data).hexdigest()
            if sha != meta.get("sha256") or len(data) != meta.get("taille"):
                divergences.append(rel)
            else:
                verifies += 1
        surplus = sorted(noms - set(attendus))
    ok = not divergences and not manquants and not surplus
    return {"ok": ok, "verifies": verifies, "divergences": sorted(divergences),
            "manquants": sorted(manquants), "surplus": surplus,
            "empreinte_globale": manifeste.get("empreinte_globale", "")}


# ── ORCHESTRATEUR (item 20 complet) ──────────────────────────────────────────────────────────
def creer_archive_portable(root: str | Path, cible: str | Path, *, version: str = "",
                           git_sha: str | None = None, exiger_arret: bool = True,
                           pid_vivant=None, horloge=time.time) -> dict:
    """Enchaine les 9 etapes de l'item 20 et rend un verdict. Leve ArchiveRefuseeError sur refus dur
    (writers vivants, session ACTIVE, chemin absolu residuel). Ne fabrique JAMAIS une archive
    partielle : au moindre doute, on refuse et rien n'est ecrit."""
    root = Path(root)
    # 1+2 : refus durs AVANT tout travail couteux.
    arretes, motifs = preuve_arret(root, pid_vivant=pid_vivant)
    vivants = [m for m in motifs if m not in _MARQUEURS_REGISTRE]
    if exiger_arret and vivants:                       # de VRAIS writers vivants -> refus dur
        raise ArchiveRefuseeError("writers encore vivants: %s" % ", ".join(vivants))
    note_arret = "PROUVE_ARRETE" if arretes else ("QUIESCENT_SANS_REGISTRE (%s)" % ",".join(motifs))
    actives = sessions_actives(root)
    if actives:
        raise ArchiveRefuseeError("sessions ACTIVE (a cloturer d'abord): %s" % ", ".join(actives))
    # 3 : WAL checkpoint.
    sqlite_prep = preparer_sqlite(root)
    echecs_sql = [d for d in sqlite_prep if not d.get("ok")]
    if echecs_sql:
        raise ArchiveRefuseeError("SQLite non checkpointables: %s"
                                  % ", ".join(d["base"] for d in echecs_sql))
    # 4+5 : selection.
    inclus, exclus = lister_pour_archive(root)
    # 7 : manifeste.
    manifeste = construire_manifeste(root, inclus, exclus, version=version,
                                     git_sha=git_sha, horloge=horloge)
    # 6+8 : ecriture (neutralisation + refus si chemin absolu residuel).
    ecrit = ecrire_archive(root, cible, inclus, manifeste)
    # 9 : re-verification.
    verif = reverifier_archive(cible)
    if not verif.get("ok"):
        Path(cible).unlink(missing_ok=True)
        raise ArchiveRefuseeError("re-verification KO: %s" % json.dumps(verif, ensure_ascii=False))
    return {"archive": str(cible), "inclus": len(inclus), "exclus": len(exclus),
            "sqlite": sqlite_prep, "empreinte_globale": manifeste["empreinte_globale"],
            "arret": note_arret, "verification": verif, "manifeste": NOM_MANIFESTE,
            "ecriture": ecrit}


def _nom_archive_versionne(root: Path, manifeste_version: str, ts_ms: int) -> str:
    v = (manifeste_version or "0.0.0-dev").replace(" ", "_")
    return "hypersmart_portable_%s_%d.zip" % (v, ts_ms)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="archive_portable",
                                 description="Archive portable HyperSmart (item 20) + re-verif (item 22).")
    ap.add_argument("--racine", default=".", help="racine du projet (defaut: dossier courant)")
    ap.add_argument("--sortie", default="", help="chemin .zip (defaut: dist/ versionne)")
    ap.add_argument("--version", default="", help="version HyperSmart a graver dans le manifeste")
    ap.add_argument("--git-sha", default=None, help="SHA git (defaut: lu dans .git)")
    ap.add_argument("--sans-preuve-arret", action="store_true",
                    help="ne PAS exiger la preuve d'arret (build de test uniquement)")
    ap.add_argument("--verifier", default="", help="re-verifie une archive existante et sort")
    args = ap.parse_args(argv)

    if args.verifier:
        verif = reverifier_archive(args.verifier)
        print(json.dumps(verif, ensure_ascii=False, indent=2))
        return 0 if verif.get("ok") else 4

    root = Path(args.racine).resolve()
    version = args.version or _version_projet(root)
    if args.sortie:
        cible = Path(args.sortie)
    else:
        cible = root / "dist" / _nom_archive_versionne(root, version, int(time.time() * 1000))
    try:
        res = creer_archive_portable(root, cible, version=version, git_sha=args.git_sha,
                                     exiger_arret=not args.sans_preuve_arret)
    except ArchiveRefuseeError as exc:
        print("ARCHIVE_REFUSEE: %s" % exc, file=sys.stderr)
        return 5
    except Exception as exc:                            # noqa: BLE001 — tout autre echec = code 1
        print("ARCHIVE_ERREUR: %s" % exc, file=sys.stderr)
        return 1
    print("ARCHIVE_PORTABLE_OK %s" % res["archive"])
    print(json.dumps({k: v for k, v in res.items() if k != "manifeste"},
                     ensure_ascii=False, indent=2))
    return 0


__all__ = ["SCHEMA_MANIFESTE", "NOM_MANIFESTE", "ArchiveRefuseeError", "preuve_arret",
           "writers_vivants", "sessions_actives", "checkpoint_wal_sqlite", "preparer_sqlite", "est_exclu",
           "lister_pour_archive", "neutraliser_metadonnees", "chemins_absolus_residuels",
           "construire_manifeste", "ecrire_archive", "reverifier_archive",
           "creer_archive_portable", "main"]


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
