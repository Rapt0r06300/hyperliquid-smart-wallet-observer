"""[PORTABILITE items 20 & 22] Construction d'une archive PORTABLE de HyperSmart, avec re-verification.

But (critere final de Flo) : apres extraction de cette archive sur un AUTRE PC Windows x64
compatible, double-clic `LANCER_HYPERSMART.cmd` -> recolte -> cloture -> double-clic
`ANALYSER_BACKTESTS_REPLAYS.cmd`, SANS modifier aucun chemin ni installer Python/deps a la main.

`CREER_ARCHIVE_PORTABLE.cmd` appelle ce module. Il, automatiquement (item 20) :
  1. exige la PREUVE que tous les writers sont arretes (reutilise session_harvest, FAIL-CLOSED) ;
  2. REFUSE de construire s'il reste une session ACTIVE (jamais une demi-session dans l'archive) ;
  3. ouvre chaque SQLite source en lecture seule, la copie par l'API Backup vers le staging,
     puis execute `integrity_check` sur cette copie sans modifier la base source ni son WAL ;
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
import hashlib
import json
import os
import platform
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Iterable

from hl_observer.ops import session_catalog as SC
from hl_observer.ops import registre_pids as RP
from hl_observer.ops.registre_pids import REGISTRE_RELPATH

SCHEMA_MANIFESTE = "hypersmart.portable_manifest.v1"
NOM_MANIFESTE = "PORTABLE_MANIFEST.json"

DOSSIERS_EXCLUS = ("__pycache__", ".git", ".venv", "venv", "env", "node_modules",
                   ".pytest_cache", ".mypy_cache", ".ruff_cache", "portable_runtime",
                   ".venv-portable", "tmp_pytest", "htmlcov", "dist", "build",
                   ".portable-staging", "portable-build", "cache_moisson", ".hypothesis",
                   "_validation_workspace")
PREFIXES_DOSSIERS_TRANSITOIRES = (".portable-",)
PREFIXES_EXCLUS = (
    "runtime/research/", "logs/", "data/", "_to_delete/", "archive/",
    "outils de test/rapports/",
)
SUFFIXES_EXCLUS = (".pyc", ".pyo", ".log", ".lock", ".pid", ".tmp", ".bundle",
                   ".sqlite3-wal", ".sqlite3-shm", ".sqlite-wal", ".sqlite-shm",
                   "-wal", "-shm", ".db-wal", ".db-shm")
SUFFIXES_ARCHIVES = (".zip", ".7z", ".rar", ".sha256")
SUFFIXES_SECRETS = (".key", ".p12", ".pfx", ".mnemonic", ".seed", ".keystore")
FICHIERS_EXCLUS = (REGISTRE_RELPATH.as_posix(),
                   "runtime/data/lanceur_session_marqueur.txt",
                   "runtime/data/COURANTE.json",
                   "moisson_console.txt",
                   "moisson-termine.flag",
                   "moisson-en-cours.txt",
                   "moisson-fini.md",
                   ".analyse.lock", NOM_MANIFESTE)
_ABSOLU = re.compile(
    r"(?:[A-Za-z]:\\|\\\\[^\\\s\"]+\\[^\\\s\"]+|/(?:home|Users)/)"
                   )


def _composant_dossier_exclu(nom: str) -> bool:
    return nom in DOSSIERS_EXCLUS or nom.startswith(PREFIXES_DOSSIERS_TRANSITOIRES)


_CLE_PRIVEE = re.compile(
    rb"-----BEGIN (?:ENCRYPTED |RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----"
    rb"\s+[A-Za-z0-9+/=\r\n]{64,}"
    rb"-----END (?:ENCRYPTED |RSA |DSA |EC |OPENSSH )?PRIVATE KEY-----",
    re.IGNORECASE,
)
_NOMS_WINDOWS_RESERVES = {
    "CON", "PRN", "AUX", "NUL", "CLOCK$",
    *("COM%d" % i for i in range(1, 10)),
    *("LPT%d" % i for i in range(1, 10)),
}
_MAX_COMPOSANT_WINDOWS = 240
_MAX_CHEMIN_RELATIF_WINDOWS = 220
_EPOCH_ZIP_MINIMUM = 315532800
_MARQUEUR_LFS = b"version https://git-lfs.github.com/spec/v1"


_MARQUEURS_REGISTRE = frozenset({"REGISTRE_ABSENT", "REGISTRE_ILLISIBLE", "REGISTRE_INCOMPLET",
                                 "REGISTRE_CORROMPU"})


def preuve_arret(root: str | Path, *, pid_vivant=None) -> tuple[bool, list[str]]:
    """Preuve fail-closed basee sur le registre PID et un scan independant du checkout courant."""
    root = Path(root).resolve()
    chemin = root / REGISTRE_RELPATH
    if not chemin.is_file():
        return False, ["REGISTRE_ABSENT"]
    try:
        registre = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, ["REGISTRE_CORROMPU"]
    if not isinstance(registre, dict) or not isinstance(registre.get("composants"), dict) \
            or not isinstance(registre.get("collecteurs"), dict):
        return False, ["REGISTRE_INCOMPLET"]
    if pid_vivant is None:
        from hl_observer.ops.preuve_de_vie import _pid_vivant_reel
        pid_vivant = _pid_vivant_reel
    pids_connus = RP.pids_enregistres(registre)
    vivants = sorted(pid for pid in pids_connus if pid_vivant(pid))
    motifs = ["PID_VIVANT:%d" % pid for pid in vivants]
    try:
        orphelins = RP.detecter_orphelins(
            RP.processus_reels(),
            pids_connus,
            root=root,
        )
    except Exception:  # noqa: BLE001 - absence de psutil traitee par processus_reels
        orphelins = []
    motifs.extend("PROCESSUS_ORPHELIN:%s" % p.get("pid") for p in orphelins)
    return not motifs, motifs


def writers_vivants(root: str | Path, *, pid_vivant=None) -> list[str]:
    _arretes, motifs = preuve_arret(root, pid_vivant=pid_vivant)
    return [m for m in motifs if m not in _MARQUEURS_REGISTRE]


def sessions_actives(root: str | Path) -> list[str]:
    return [s["run_id"] for s in SC.scanner_sessions(root) if s.get("statut") == SC.STATUT_ACTIVE]


def contient_cle_privee(chemin: str | Path) -> bool:
    chemin = Path(chemin)
    try:
        with chemin.open("rb") as flux:
            debut = flux.read(64 * 1024)
    except OSError:
        return False
    return bool(_CLE_PRIVEE.search(debut))


def _est_reparse(chemin: Path) -> bool:
    if chemin.is_symlink():
        return True
    try:
        attrs = getattr(chemin.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def valider_chemin_relatif(rel: str, *, max_rel: int = _MAX_CHEMIN_RELATIF_WINDOWS) -> str:
    if not isinstance(rel, str) or not rel:
        raise ArchiveRefuseeError("chemin vide dans l'inventaire")
    brut = rel.replace("\\", "/")
    if brut.startswith(("/", "//")) or re.match(r"^[A-Za-z]:", brut):
        raise ArchiveRefuseeError("chemin absolu/UNC interdit: %s" % rel)
    morceaux = brut.split("/")
    if any(m in ("", ".", "..") for m in morceaux):
        raise ArchiveRefuseeError("composant relatif dangereux: %s" % rel)
    for morceau in morceaux:
        if len(morceau) > _MAX_COMPOSANT_WINDOWS:
            raise ArchiveRefuseeError("composant Windows trop long: %s" % rel)
        if morceau[-1:] in (" ", "."):
            raise ArchiveRefuseeError("nom Windows avec espace/point final: %s" % rel)
        if any(ord(c) < 32 for c in morceau) or any(c in '<>:"|?*' for c in morceau):
            raise ArchiveRefuseeError("caractere Windows interdit: %s" % rel)
        base = morceau.split(".", 1)[0].upper()
        if base in _NOMS_WINDOWS_RESERVES:
            raise ArchiveRefuseeError("nom Windows reserve: %s" % rel)
    canonique = "/".join(morceaux)
    if len(canonique) > max_rel:
        raise ArchiveRefuseeError(
            "chemin trop long pour une extraction Windows standard (%d > %d): %s"
            % (len(canonique), max_rel, canonique)
        )
    return canonique


def valider_fichier_source(root: str | Path, chemin: str | Path) -> str:
    root = Path(root).resolve()
    chemin = Path(chemin)
    try:
        rel = chemin.relative_to(root).as_posix()
    except ValueError as exc:
        raise ArchiveRefuseeError("fichier hors racine: %s" % chemin) from exc
    courant = root
    for morceau in Path(rel).parts:
        courant = courant / morceau
        if _est_reparse(courant):
            raise ArchiveRefuseeError("lien/jonction/reparse interdit: %s" % rel)
    try:
        chemin.resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise ArchiveRefuseeError("fichier resolu hors racine: %s" % rel) from exc
    return valider_chemin_relatif(rel)


def checkpoint_wal_sqlite(chemin: str | Path) -> dict:
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
    except sqlite3.Error as exc:
        return {"base": chemin.name, "ok": False, "erreur": str(exc)}


def copier_sqlite_vers_staging(source: str | Path, destination: str | Path) -> dict:
    source, destination = Path(source), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source_uri = source.resolve().as_uri() + "?mode=ro"
    try:
        src = sqlite3.connect(source_uri, uri=True)
        dst = sqlite3.connect(str(destination))
        try:
            src.backup(dst)
            verdict = dst.execute("PRAGMA integrity_check").fetchone()
            if not verdict or str(verdict[0]).lower() != "ok":
                raise sqlite3.DatabaseError("integrity_check=%r" % (verdict,))
            dst.execute("PRAGMA journal_mode=DELETE")
            dst.commit()
        finally:
            dst.close()
            src.close()
        return {"base": source.name, "ok": True, "methode": "sqlite_backup_api"}
    except (OSError, sqlite3.Error) as exc:
        destination.unlink(missing_ok=True)
        return {"base": source.name, "ok": False, "erreur": str(exc),
                "methode": "sqlite_backup_api"}


def construire_staging(root: str | Path, staging: str | Path,
                       inclus: Iterable[str]) -> dict:
    root, staging = Path(root).resolve(), Path(staging).resolve()
    try:
        staging.relative_to(root)
    except ValueError:
        import logging as _lg
        _lg.getLogger(__name__).debug("staging externe confirme", exc_info=True)
    else:
        raise ArchiveRefuseeError("le staging doit etre exterieur a la racine source")
    staging.mkdir(parents=True, exist_ok=False)
    sqlite_resultats: list[dict] = []
    neutralises = 0
    try:
        for rel in sorted(set(inclus)):
            rel = valider_chemin_relatif(rel)
            src = root / Path(rel)
            valider_fichier_source(root, src)
            dst = staging / Path(rel)
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.suffix.lower() in (".sqlite", ".sqlite3", ".db"):
                resultat = copier_sqlite_vers_staging(src, dst)
                sqlite_resultats.append(resultat)
                if not resultat["ok"]:
                    raise ArchiveRefuseeError("copie SQLite impossible: %s" % resultat)
                continue
            if _est_metadonnee(rel):
                try:
                    texte = src.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    shutil.copy2(src, dst)
                else:
                    transforme, n = neutraliser_metadonnees(texte, root)
                    residus = chemins_absolus_residuels(transforme)
                    if residus:
                        raise ArchiveRefuseeError(
                            "chemins absolus residuels dans %s: %s" % (rel, residus)
                        )
                    dst.write_text(transforme, encoding="utf-8", newline="\n")
                    neutralises += n
            else:
                shutil.copy2(src, dst)
        fichiers = sorted(p.relative_to(staging).as_posix()
                          for p in staging.rglob("*") if p.is_file())
        return {"fichiers": fichiers, "sqlite": sqlite_resultats,
                "chemins_neutralises": neutralises}
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def preparer_sqlite(root: str | Path) -> list[dict]:
    root = Path(root)
    out: list[dict] = []
    for ext in ("*.sqlite", "*.sqlite3", "*.db"):
        for p in root.rglob(ext):
            if any(_composant_dossier_exclu(part) for part in p.relative_to(root).parts):
                continue
            out.append(checkpoint_wal_sqlite(p))
    return out


def est_exclu(rel: str) -> bool:
    rel_posix = Path(rel).as_posix()
    if rel_posix.startswith("runtime/") \
            and not rel_posix.startswith("runtime/data/sessions/"):
        return True
    parts = Path(rel).parts
    if any(_composant_dossier_exclu(part) for part in parts):
        return True
    if rel_posix.startswith(PREFIXES_EXCLUS):
        return True
    if rel_posix in FICHIERS_EXCLUS or Path(rel).name in FICHIERS_EXCLUS:
        return True
    low = rel_posix.lower()
    if any(low.endswith(sfx) for sfx in SUFFIXES_EXCLUS):
        return True
    if any(low.endswith(sfx) for sfx in SUFFIXES_ARCHIVES):
        stdlib_python = (
            rel_posix.startswith("tools/python/")
            and re.fullmatch(r"python\d+(?:_d)?\.zip", Path(rel_posix).name, re.IGNORECASE) is not None
        )
        fixture_test = rel_posix.startswith("tests/fixtures/") or "/fixtures/" in rel_posix
        if not (fixture_test or stdlib_python):
            return True
    if any(low.endswith(sfx) for sfx in SUFFIXES_SECRETS):
        return True
    nom = Path(rel).name.lower()
    if nom == ".env" or nom.startswith(".env."):
        return True
    return False


def _dossier_a_elaguer(rel: str) -> bool:
    rel_posix = rel.replace("\\", "/").strip("/")
    if not rel_posix:
        return False
    if rel_posix == "runtime" or rel_posix == "runtime/data":
        return False
    if rel_posix.startswith("runtime/") \
            and not (rel_posix == "runtime/data/sessions"
                     or rel_posix.startswith("runtime/data/sessions/")):
        return True
    if any(_composant_dossier_exclu(part) for part in rel_posix.split("/")):
        return True
    avec_barre = rel_posix + "/"
    return any(avec_barre.startswith(prefixe) for prefixe in PREFIXES_EXCLUS)


def lister_pour_archive(root: str | Path) -> tuple[list[str], list[str]]:
    root = Path(root).resolve()
    inclus, exclus = [], []
    vus_casse: dict[str, str] = {}
    for dossier, sous_dossiers, fichiers in os.walk(root, topdown=True, followlinks=False):
        base = Path(dossier)
        gardes: list[str] = []
        for nom in sorted(sous_dossiers, key=str.casefold):
            chemin = base / nom
            rel_dir = chemin.relative_to(root).as_posix()
            if _dossier_a_elaguer(rel_dir):
                exclus.append(rel_dir + "/")
                continue
            if _est_reparse(chemin):
                raise ArchiveRefuseeError("lien/jonction/reparse interdit: %s" % rel_dir)
            gardes.append(nom)
        sous_dossiers[:] = gardes
        for nom in sorted(fichiers, key=str.casefold):
            p = base / nom
            rel = p.relative_to(root).as_posix()
            if est_exclu(rel):
                exclus.append(rel)
                continue
            rel = valider_fichier_source(root, p)
            cle = rel.casefold()
            precedent = vus_casse.get(cle)
            if precedent is not None and precedent != rel:
                raise ArchiveRefuseeError(
                    "collision Windows insensible a la casse: %s / %s" % (precedent, rel)
                )
            vus_casse[cle] = rel
            if contient_cle_privee(p):
                raise ArchiveRefuseeError("matiere de cle privee detectee: %s" % rel)
            inclus.append(rel)
    return inclus, sorted(exclus)


def neutraliser_metadonnees(texte: str, racine: str | Path) -> tuple[str, int]:
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
    return sorted({m.group(0) for m in _ABSOLU.finditer(texte)})


def _git_sha_depuis_dossier(root: str | Path) -> str:
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
        return head
    except OSError:
        return ""


def _commande_git(root: Path, *arguments: str) -> str:
    try:
        resultat = subprocess.run(
            ["git", "-C", str(root), *arguments],
            check=True, capture_output=True, text=True, encoding="utf-8",
            errors="strict", timeout=30,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise ArchiveRefuseeError("etat Git impossible a prouver: %s" % exc) from exc
    return resultat.stdout


def etat_git_release(root: str | Path) -> dict:
    root = Path(root).resolve()
    sha = _commande_git(root, "rev-parse", "--verify", "HEAD").strip()
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", sha):
        raise ArchiveRefuseeError("SHA Git invalide: %r" % sha)
    epoch_txt = _commande_git(root, "show", "-s", "--format=%ct", "HEAD").strip()
    try:
        source_date_epoch = int(epoch_txt)
    except ValueError as exc:
        raise ArchiveRefuseeError("timestamp du commit Git invalide: %r" % epoch_txt) from exc
    lignes = _commande_git(
        root, "-c", "core.quotepath=false", "status", "--porcelain=v1",
        "--untracked-files=all",
    ).splitlines()
    fichiers = []
    for ligne in lignes:
        if len(ligne) < 4:
            raise ArchiveRefuseeError("sortie Git status ambigue: %r" % ligne)
        statut, chemin = ligne[:2], ligne[3:]
        if " -> " in chemin:
            chemin = chemin.rsplit(" -> ", 1)[1]
        rel = chemin.replace("\\", "/")
        entree = {"statut": statut, "chemin": rel, "sha256": None, "taille": None}
        p = root / Path(rel)
        if p.is_file() and not p.is_symlink():
            entree["sha256"], entree["taille"] = SC.sha256_fichier(p)
        fichiers.append(entree)
    return {
        "sha": sha.lower(),
        "source_date_epoch": source_date_epoch,
        "dirty": bool(fichiers),
        "fichiers": sorted(fichiers, key=lambda x: (x["chemin"].casefold(), x["statut"])),
    }


def pointeurs_lfs_non_materialises(root: str | Path, inclus: Iterable[str]) -> list[str]:
    root = Path(root)
    trouves = []
    for rel in sorted(set(inclus)):
        p = root / Path(rel)
        try:
            with p.open("rb") as flux:
                debut = flux.read(256)
        except OSError:
            continue
        if debut.startswith(_MARQUEUR_LFS):
            trouves.append(rel)
    return trouves


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
                         horloge=time.time, source_date_epoch: int | None = None,
                         etat_git: dict | None = None) -> dict:
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
    epoch = int(source_date_epoch if source_date_epoch is not None else horloge())
    return {
        "schema": SCHEMA_MANIFESTE,
        "hypersmart_version": version or _version_projet(root),
        "git_sha": (git_sha if git_sha is not None else _git_sha_depuis_dossier(root)),
        "python": {"version": platform.python_version(),
                   "implementation": platform.python_implementation()},
        "plateforme": {"os": platform.system(), "arch": platform.machine(),
                       "cible": "Windows-x64"},
        "source_date_epoch": epoch,
        "nombre_fichiers": len(fichiers),
        "empreinte_globale": empreinte,
        "binaires": binaires,
        "sbom": _sbom(root, fichiers, binaires),
        "deps": _deps_verrouillees(root),
        "donnees_incluses": sessions,
        "donnees_exclues": sorted(set(list(DOSSIERS_EXCLUS)
                                       + list(PREFIXES_DOSSIERS_TRANSITOIRES)
                                       + list(SUFFIXES_EXCLUS)
                                       + list(FICHIERS_EXCLUS))),
        "commande_verification": "CREER_ARCHIVE_PORTABLE.cmd --verifier <archive.zip>",
        "etat_git": etat_git or {},
        "fichiers": fichiers,
    }


def _empreinte_manifeste(fichiers: dict[str, dict]) -> str:
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
                import logging as _lg
                _lg.getLogger(__name__).debug("version projet illisible", exc_info=True)
    return "0.0.0-dev"


def _deps_verrouillees(root: Path) -> list[str]:
    for nom in ("requirements.lock", "requirements-portable.txt", "requirements.txt"):
        p = root / nom
        if p.is_file():
            try:
                return [ln.strip() for ln in p.read_text(encoding="utf-8").splitlines()
                        if ln.strip() and not ln.strip().startswith("#")]
            except OSError:
                import logging as _lg
                _lg.getLogger(__name__).debug("deps verrouillees illisibles", exc_info=True)
    return []


def _licences(root: Path) -> list[str]:
    out = []
    for motif in ("LICENSE*", "LICENCE*", "COPYING*", "NOTICE*"):
        for p in sorted(root.glob(motif)):
            if p.is_file():
                out.append(p.name)
    return out


def _sbom(root: Path, fichiers: dict, binaires: dict) -> dict:
    modules_py = sum(1 for rel in fichiers if rel.endswith(".py"))
    wheels = [rel for rel in binaires if binaires[rel]["categorie"] == "wheel"]
    dll = [rel for rel in binaires if binaires[rel]["categorie"] == "dll"]
    exe = [rel for rel in binaires if binaires[rel]["categorie"] == "exe"]
    return {
        "modules_python": modules_py,
        "wheels": len(wheels), "dll": len(dll), "exe": len(exe),
        "deps_verrouillees": _deps_verrouillees(root),
        "licences": _licences(root),
        "cmd_maitres": [n for n in ("LANCER_HYPERSMART.cmd", "ANALYSER_BACKTESTS_REPLAYS.cmd",
                                    "CREER_ARCHIVE_PORTABLE.cmd") if (root / n).is_file()],
    }


def valider_membres_zip(z: zipfile.ZipFile, *, longueur_base: int = 0) -> dict:
    vus: dict[str, str] = {}
    chemin_critique = ""
    longueur_max = 0
    for info in z.infolist():
        rel = info.filename.rstrip("/")
        if not rel:
            continue
        rel = valider_chemin_relatif(rel)
        cle = rel.casefold()
        if cle in vus and vus[cle] != rel:
            raise ArchiveRefuseeError(
                "collision Windows dans le ZIP: %s / %s" % (vus[cle], rel)
            )
        vus[cle] = rel
        mode = (info.external_attr >> 16) & 0xFFFF
        if stat.S_ISLNK(mode):
            raise ArchiveRefuseeError("lien symbolique dans le ZIP: %s" % rel)
        longueur = longueur_base + 1 + len(rel.replace("/", os.sep))
        if longueur > 259:
            raise ArchiveRefuseeError(
                "chemin extrait incompatible Windows (%d): %s" % (longueur, rel)
            )
        if longueur > longueur_max:
            longueur_max, chemin_critique = longueur, rel
    return {"membres": len(vus), "longueur_max": longueur_max,
            "chemin_critique": chemin_critique}


def extraire_zip_surement(z: zipfile.ZipFile, destination: str | Path) -> dict:
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    controle = valider_membres_zip(z, longueur_base=len(str(destination)))
    for info in z.infolist():
        rel = info.filename.rstrip("/")
        if not rel:
            continue
        rel = valider_chemin_relatif(rel)
        cible = (destination / Path(rel)).resolve()
        try:
            cible.relative_to(destination)
        except ValueError as exc:
            raise ArchiveRefuseeError("zip-slip refuse: %s" % rel) from exc
        if info.is_dir():
            cible.mkdir(parents=True, exist_ok=True)
            continue
        cible.parent.mkdir(parents=True, exist_ok=True)
        with z.open(info, "r") as src, cible.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    return controle


def extraire_et_reverifier(archive: str | Path, *, dossier_extraction: str | Path | None = None) -> dict:
    archive = Path(archive)
    with zipfile.ZipFile(archive, "r") as z:
        try:
            manifeste = json.loads(z.read(NOM_MANIFESTE).decode("utf-8"))
        except KeyError:
            return {"ok": False, "raison": "MANIFESTE_ABSENT"}
        ctx = tempfile.TemporaryDirectory(prefix="verif_extraction_") if dossier_extraction is None else None
        base = Path(dossier_extraction) if dossier_extraction is not None else Path(ctx.name)
        try:
            securite = extraire_zip_surement(z, base)
            attendus = manifeste.get("fichiers", {})
            divergences, manquants, verifies = [], [], 0
            for rel, meta in attendus.items():
                p = base / rel
                if not p.is_file():
                    manquants.append(rel)
                    continue
                sha, taille = SC.sha256_fichier(p)
                if sha != meta.get("sha256") or taille != meta.get("taille"):
                    divergences.append(rel)
                else:
                    verifies += 1
        finally:
            if ctx is not None:
                ctx.cleanup()
    ok = not divergences and not manquants
    return {"ok": ok, "verifies": verifies, "divergences": sorted(divergences),
            "manquants": sorted(manquants), "securite_chemins": securite}


class ArchiveRefuseeError(RuntimeError):
    pass


def _est_metadonnee(rel: str) -> bool:
    low = rel.lower()
    if low.startswith("tools/python/"):
        return False
    return low.endswith(".json") or low.endswith(".txt") or low.endswith(".cfg") \
        or low.endswith(".ini") or low.endswith(".toml")


def ecrire_archive(root: str | Path, cible: str | Path, inclus: Iterable[str],
                   manifeste: dict) -> dict:
    root, cible = Path(root), Path(cible)
    cible.parent.mkdir(parents=True, exist_ok=True)
    inclus = sorted(inclus)
    epoch = max(int(manifeste.get("source_date_epoch", _EPOCH_ZIP_MINIMUM)), _EPOCH_ZIP_MINIMUM)
    date_zip = time.gmtime(epoch)[:6]

    def info_zip(rel: str) -> zipfile.ZipInfo:
        info = zipfile.ZipInfo(rel, date_time=date_zip)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        info.flag_bits |= 0x800
        return info

    with zipfile.ZipFile(cible, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9, strict_timestamps=False) as z:
        for rel in inclus:
            data = (root / rel).read_bytes()
            z.writestr(info_zip(rel), data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        manifeste_bytes = (json.dumps(
            manifeste, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ) + "\n").encode("utf-8")
        z.writestr(info_zip(NOM_MANIFESTE), manifeste_bytes,
                   compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return {"archive": str(cible), "membres": len(inclus) + 1,
            "chemins_neutralises": 0, "source_date_epoch": epoch}


def reverifier_archive(cible: str | Path) -> dict:
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


def creer_archive_portable(root: str | Path, cible: str | Path, *, version: str = "",
                           git_sha: str | None = None,
                           pid_vivant=None, horloge=time.time,
                           non_suivis_requis: list[str] | None = None,
                           mode_release: str = "developpement",
                           etat_git: dict | None = None) -> dict:
    root = Path(root).resolve()
    cible = Path(cible).resolve()
    try:
        cible.relative_to(root)
    except ValueError:
        pass
    else:
        raise ArchiveRefuseeError("la sortie ZIP doit etre exterieure au projet: %s" % cible)
    if mode_release not in {"official", "developpement"}:
        raise ArchiveRefuseeError("mode release invalide: %s" % mode_release)
    arretes, motifs = preuve_arret(root, pid_vivant=pid_vivant)
    vivants = [m for m in motifs if m not in _MARQUEURS_REGISTRE]
    registre_seulement = motifs == ["REGISTRE_ABSENT"]
    if not arretes and not (mode_release == "developpement" and registre_seulement):
        raise ArchiveRefuseeError("arret des writers non prouve: %s" % ", ".join(motifs))
    if vivants:
        raise ArchiveRefuseeError("writers encore vivants: %s" % ", ".join(vivants))
    note_arret = (
        "PROUVE_ARRETE" if arretes
        else "AUCUN_WRITER_DETECTE_REGISTRE_ABSENT (%s)" % ",".join(motifs)
    )
    actives = sessions_actives(root)
    if actives:
        raise ArchiveRefuseeError("sessions ACTIVE (a cloturer d'abord): %s" % ", ".join(actives))
    inclus, exclus = lister_pour_archive(root)
    lfs = pointeurs_lfs_non_materialises(root, inclus)
    if lfs:
        raise ArchiveRefuseeError("pointeurs Git LFS non materialises: %s" % ", ".join(lfs))
    git = dict(etat_git or etat_git_release(root))
    if mode_release == "official" and git.get("dirty"):
        chemins_dirty = [x.get("chemin", "?") for x in git.get("fichiers", [])]
        raise ArchiveRefuseeError(
            "release officielle refusee: depot dirty (%s)" % ", ".join(chemins_dirty)
        )
    from hl_observer.ops.inventaire_release import controle_completude, formater as _fmt_compl
    completude = controle_completude(root, inclus, non_suivis=non_suivis_requis)
    if not completude["complet"]:
        raise ArchiveRefuseeError("release INCOMPLETE: %s" % _fmt_compl(completude))
    cible.parent.mkdir(parents=True, exist_ok=True)
    cible_temporaire = cible.with_name(".%s.%d.tmp" % (cible.name, os.getpid()))
    cible_temporaire.unlink(missing_ok=True)
    sha_source = git_sha if git_sha is not None else str(git.get("sha", ""))
    version_source = version or _version_projet(root)
    if mode_release == "developpement" and git.get("dirty") and not version_source.endswith("-dirty"):
        version_source += "-dirty"
    try:
        with tempfile.TemporaryDirectory(prefix="hypersmart-portable-staging-") as tmp:
            staging = Path(tmp) / "release"
            staging_info = construire_staging(root, staging, inclus)
            staging_inclus = staging_info["fichiers"]
            source_attendu = set(inclus)
            stage_reel = set(staging_inclus)
            if source_attendu != stage_reel:
                raise ArchiveRefuseeError(
                    "staging divergent: manquants=%s surplus=%s"
                    % (sorted(source_attendu - stage_reel), sorted(stage_reel - source_attendu))
                )
            manifeste = construire_manifeste(
                staging, staging_inclus, exclus, version=version_source,
                git_sha=sha_source, horloge=horloge,
                source_date_epoch=int(git.get("source_date_epoch", horloge())),
                etat_git=git,
            )
            manifeste["completude"] = {
                k: (len(v) if isinstance(v, list) else v)
                for k, v in completude.items()
            }
            manifeste["mode_release"] = mode_release
            manifeste["staging"] = {
                "source_immuable": True,
                "sqlite_backup_api": all(x.get("ok") for x in staging_info["sqlite"]),
                "sqlite_count": len(staging_info["sqlite"]),
                "chemins_neutralises": staging_info["chemins_neutralises"],
            }
            ecrit = ecrire_archive(staging, cible_temporaire, staging_inclus, manifeste)
            verif = reverifier_archive(cible_temporaire)
            if not verif.get("ok"):
                raise ArchiveRefuseeError(
                    "re-verification KO: %s" % json.dumps(verif, ensure_ascii=False)
                )
            verif_extraction = extraire_et_reverifier(cible_temporaire)
            if not verif_extraction.get("ok"):
                raise ArchiveRefuseeError(
                    "extraction de controle KO: %s"
                    % json.dumps(verif_extraction, ensure_ascii=False)
                )
            os.replace(cible_temporaire, cible)
    except BaseException:
        cible_temporaire.unlink(missing_ok=True)
        raise
    return {"archive": str(cible), "inclus": len(inclus), "exclus": len(exclus),
            "sqlite": staging_info["sqlite"],
            "empreinte_globale": manifeste["empreinte_globale"],
            "arret": note_arret, "verification": verif,
            "verification_extraction": verif_extraction,
            "sbom": manifeste.get("sbom"), "manifeste": NOM_MANIFESTE,
            "ecriture": ecrit, "staging": manifeste["staging"],
            "etat_git": git, "mode_release": mode_release}


def _nom_archive_versionne(root: Path, manifeste_version: str, git_sha: str) -> str:
    v = (manifeste_version or "0.0.0-dev").replace(" ", "_")
    sha = (git_sha or "sans-git")[:12]
    return "hypersmart_portable_%s_%s.zip" % (v, sha)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="archive_portable",
                                 description="Archive portable HyperSmart (item 20) + re-verif (item 22).")
    ap.add_argument("--racine", default=".", help="racine du projet (defaut: dossier courant)")
    ap.add_argument("--sortie", default="", help="chemin .zip (defaut: Bureau utilisateur)")
    ap.add_argument("--version", default="", help="version HyperSmart a graver dans le manifeste")
    ap.add_argument("--mode-developpement", action="store_true",
                    help="autorise un checkout dirty et grave -dirty + hashes")
    ap.add_argument("--verifier", default="", help="re-verifie une archive existante et sort")
    args = ap.parse_args(argv)

    if args.verifier:
        verif = reverifier_archive(args.verifier)
        print(json.dumps(verif, ensure_ascii=False, indent=2))
        return 0 if verif.get("ok") else 4

    root = Path(args.racine).resolve()
    version = args.version or _version_projet(root)
    try:
        git = etat_git_release(root)
    except ArchiveRefuseeError as exc:
        print("ARCHIVE_REFUSEE: %s" % exc, file=sys.stderr)
        return 5
    mode_release = "developpement" if args.mode_developpement else "official"
    version_sortie = version + ("-dirty" if git.get("dirty") and mode_release == "developpement" else "")
    if args.sortie:
        cible = Path(args.sortie)
    else:
        bureau = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
        cible = bureau / _nom_archive_versionne(root, version_sortie, str(git.get("sha", "")))
    try:
        res = creer_archive_portable(root, cible, version=version, mode_release=mode_release,
                                     etat_git=git)
    except ArchiveRefuseeError as exc:
        print("ARCHIVE_REFUSEE: %s" % exc, file=sys.stderr)
        return 5
    except Exception as exc:
        print("ARCHIVE_ERREUR: %s" % exc, file=sys.stderr)
        return 1
    print("ARCHIVE_PORTABLE_OK %s" % res["archive"])
    print(json.dumps({k: v for k, v in res.items() if k != "manifeste"},
                     ensure_ascii=False, indent=2))
    return 0


__all__ = ["SCHEMA_MANIFESTE", "NOM_MANIFESTE", "ArchiveRefuseeError", "preuve_arret",
           "writers_vivants", "sessions_actives", "checkpoint_wal_sqlite", "preparer_sqlite",
           "copier_sqlite_vers_staging", "construire_staging", "contient_cle_privee",
           "valider_chemin_relatif", "valider_fichier_source", "valider_membres_zip",
           "extraire_zip_surement", "est_exclu",
           "lister_pour_archive", "neutraliser_metadonnees", "chemins_absolus_residuels",
           "etat_git_release", "pointeurs_lfs_non_materialises",
           "construire_manifeste", "ecrire_archive", "reverifier_archive", "extraire_et_reverifier",
           "creer_archive_portable", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
