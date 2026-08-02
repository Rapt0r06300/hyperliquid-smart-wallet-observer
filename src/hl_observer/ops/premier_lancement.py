"""[PORTABILITE item 21] Controles de PREMIER LANCEMENT sur un PC neuf (apres extraction de l'archive).

Repond a la question : « ce PC peut-il faire tourner HyperSmart, ici, maintenant, sans rien installer
ni modifier ? » et REGENERE l'identite machine-specifique (PID, verrous, machine-id) pour qu'un
archive copiee ne reutilise JAMAIS l'etat de la machine de build.

Controles (statut OK / INFO / AVERTISSEMENT / ECHEC) :
  - OS/arch Windows 10/11 x64      -> ECHEC seulement sur une CIBLE Windows non-x64 ; INFO ailleurs
                                      (le module reste utilisable/testable hors Windows).
  - droits d'ecriture sous racine  -> BLOQUANT (sans ecriture, ni sessions ni rapports).
  - chemin a espaces/accents        -> verifie le round-trip reel (le lanceur ancre sur %~dp0).
  - horloge coherente               -> AVERTISSEMENT si derive absurde (sonde injectable).
  - port UI (8794) libre            -> AVERTISSEMENT si occupe (restart couvre) ; sonde injectable.
  - reseau / TLS                    -> AVERTISSEMENT (l'ANALYSE marche hors-ligne ; la COLLECTE non).
  - aucune cle copiee               -> BLOQUANT : matiere de cle presente = refus (securite).
  - historique/sessions preserves   -> compte les sessions COMPLETE, ne SUPPRIME jamais de donnee.

Action : regeneration de l'identite (purge PID/verrous/marqueurs/pointeur COURANTE, machine-id neuf).
Tout est injectable -> 0 reseau en test. Le .cmd (LANCER_HYPERSMART.cmd) appelle ce module AVANT les
collecteurs ; un ECHEC bloquant stoppe le demarrage avec un diagnostic precis.
"""
from __future__ import annotations

import json
import os
import platform
import socket
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from hl_observer.ops import session_catalog as SC
from hl_observer.ops.registre_pids import REGISTRE_RELPATH

OK, INFO, AVERT, ECHEC = "OK", "INFO", "AVERTISSEMENT", "ECHEC"
PORT_UI = 8794
MACHINE_ID_RELPATH = Path("runtime") / "data" / "machine_id.txt"
# Le verrou d'instance du lanceur COURANT est VIVANT quand ce module tourne (le .cmd acquiert le
# verrou AVANT le prevol) : ne JAMAIS le purger, sinon un 2e double-clic passerait le garde anti-double
# lancement. Sa peremption est geree par son propre TTL (collection.verrou_instance), pas ici.
LOCK_INSTANCE_VIVANT = "lanceur_instance.lock"
DERIVE_HORLOGE_MAX_MS = 5 * 365 * 24 * 3600 * 1000     # 5 ans : derive « absurde » (pile morte, RTC faux)
# matiere de cle qui ne doit JAMAIS avoir ete copiee (meme paper-strict) — voir archive_portable.
_SUFFIXES_SECRETS = (".key", ".pem", ".p12", ".pfx", ".mnemonic", ".seed", ".keystore")


def _res(nom: str, statut: str, detail: str) -> dict:
    return {"nom": nom, "statut": statut, "detail": detail}


# ── CONTROLES (purs, injectables) ─────────────────────────────────────────────────────────────
def verifier_os_arch(*, systeme: str | None = None, machine: str | None = None,
                     version: str | None = None) -> dict:
    """Windows 10/11 x64. Hors Windows (dev/CI Linux) = INFO, jamais un ECHEC (le module reste testable).
    Sur Windows, une arch non-64 bits = ECHEC (le runtime embarque est x64)."""
    systeme = systeme if systeme is not None else platform.system()
    machine = (machine if machine is not None else platform.machine()) or ""
    if systeme != "Windows":
        return _res("os_arch", INFO, "cible = Windows x64 ; ici %s/%s (dev/CI, non bloquant)"
                    % (systeme, machine or "?"))
    x64 = machine.upper() in ("AMD64", "X86_64", "EM64T")
    if not x64:
        return _res("os_arch", ECHEC, "Windows non-x64 (%s) : runtime embarque incompatible" % machine)
    return _res("os_arch", OK, "Windows x64 (%s)" % machine)


def verifier_droits_ecriture(root: str | Path) -> dict:
    """BLOQUANT : ecrit reellement un fichier temoin sous la racine, puis le retire."""
    root = Path(root)
    try:
        root.mkdir(parents=True, exist_ok=True)
        temoin = root / (".ecriture_%d.tmp" % os.getpid())
        temoin.write_text("ok", encoding="utf-8")
        lu = temoin.read_text(encoding="utf-8")
        temoin.unlink()
        if lu != "ok":
            return _res("droits_ecriture", ECHEC, "relecture incoherente sous %s" % root)
        return _res("droits_ecriture", OK, "ecriture/lecture OK sous la racine")
    except OSError as exc:
        return _res("droits_ecriture", ECHEC, "ecriture impossible sous %s : %s" % (root, exc))


def verifier_chemin_espaces_accents(root: str | Path) -> dict:
    """Le dossier peut contenir espaces/accents (« Projet invest ») : on VERIFIE le round-trip reel
    d'un fichier dont le nom porte un accent, la ou est reellement pose le projet."""
    root = Path(root)
    a_espace = " " in str(root)
    a_accent = any(ord(c) > 127 for c in str(root))
    try:
        p = root / "verif_accent_é.tmp"
        p.write_text("é", encoding="utf-8")
        ok = p.read_text(encoding="utf-8") == "é"
        p.unlink()
    except OSError as exc:
        return _res("chemin", ECHEC, "chemin a accents/espaces non gere par le FS : %s" % exc)
    detail = "round-trip accent OK" + (" (chemin avec espace)" if a_espace else "") \
        + (" (chemin avec accent)" if a_accent else "")
    return _res("chemin", OK if ok else ECHEC, detail)


def verifier_horloge(*, maintenant_ms: float | None = None, reference_ms: float = 1_735_689_600_000) -> dict:
    """AVERTISSEMENT si l'horloge est absurde (avant 2025 = pile morte, ou tres loin dans le futur).
    reference_ms defaut = 2025-01-01. Sonde injectable (0 dependance a l'heure reelle en test)."""
    maintenant_ms = maintenant_ms if maintenant_ms is not None else time.time() * 1000.0
    if maintenant_ms < reference_ms:
        return _res("horloge", AVERT, "horloge anterieure a 2025 : dates de session peu fiables")
    if maintenant_ms - reference_ms > DERIVE_HORLOGE_MAX_MS:
        return _res("horloge", AVERT, "horloge tres loin dans le futur : verifier la date systeme")
    return _res("horloge", OK, "horloge coherente")


def _sonde_port_reelle(port: int) -> bool:
    """True si le port est LIBRE (bind reussit). Localhost uniquement, 0 trafic sortant."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def verifier_port(port: int = PORT_UI, *, sonde: Callable[[int], bool] | None = None) -> dict:
    """AVERTISSEMENT si le port UI est occupe (un restart le libere) — jamais bloquant."""
    sonde = sonde or _sonde_port_reelle
    libre = sonde(port)
    return _res("port_ui", OK if libre else AVERT,
                "port %d %s" % (port, "libre" if libre else "occupe (relancer / restart)"))


def verifier_reseau_tls(*, sonde: Callable[[], dict] | None = None) -> dict:
    """AVERTISSEMENT par defaut : l'ANALYSE tourne hors-ligne ; seule la COLLECTE exige le reseau+TLS.
    Une sonde peut etre injectee (le .cmd/un futur collecteur), sinon on n'invente aucun etat reseau."""
    if sonde is None:
        return _res("reseau_tls", INFO, "non sonde ici (analyse OK hors-ligne ; collecte exige reseau/TLS)")
    try:
        r = sonde()
    except Exception as exc:  # noqa: BLE001
        return _res("reseau_tls", AVERT, "sonde reseau/TLS en echec : %s" % exc)
    ok = bool(r.get("ok"))
    return _res("reseau_tls", OK if ok else AVERT, str(r.get("detail", "")) or ("OK" if ok else "indisponible"))


def verifier_aucune_cle(root: str | Path) -> dict:
    """BLOQUANT : aucune matiere de cle ne doit avoir ete copiee (extension, pas sous-chaine)."""
    root = Path(root)
    trouves: list[str] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        nom = p.name.lower()
        if nom == ".env" or nom.startswith(".env."):
            trouves.append(p.relative_to(root).as_posix())
        elif any(nom.endswith(sfx) for sfx in _SUFFIXES_SECRETS):
            trouves.append(p.relative_to(root).as_posix())
        if len(trouves) >= 20:
            break
    if trouves:
        return _res("aucune_cle", ECHEC, "matiere de cle presente (a retirer) : %s" % ", ".join(trouves))
    return _res("aucune_cle", OK, "aucune matiere de cle copiee")


def verifier_sessions_preservees(root: str | Path) -> dict:
    """Compte les sessions COMPLETE/QUARANTINED. Ne SUPPRIME jamais rien : l'historique/PnL est sacre."""
    sessions = SC.scanner_sessions(root)
    completes = [s for s in sessions if s.get("statut") == SC.STATUT_COMPLETE]
    return _res("sessions", OK, "%d session(s) dont %d COMPLETE preservees"
                % (len(sessions), len(completes)))


# ── item 10 : espace disque / imports / DLL / integrite du manifeste ──────────────────────────
def verifier_espace_disque(root: str | Path, *, min_mo: int = 200) -> dict:
    """AVERT si l'espace libre sous la racine est bas (une collecte/DB a besoin de place)."""
    import shutil
    try:
        libre_mo = shutil.disk_usage(str(root)).free // (1024 * 1024)
    except OSError as exc:
        return _res("disque", AVERT, "espace disque indeterminable : %s" % exc)
    if libre_mo < min_mo:
        return _res("disque", AVERT, "espace libre bas : %d Mo (< %d Mo)" % (libre_mo, min_mo))
    return _res("disque", OK, "espace libre : %d Mo" % libre_mo)


CRITIQUES_STDLIB = ("json", "sqlite3", "hashlib", "ssl", "ctypes", "zipfile", "socket")


def verifier_imports(modules: tuple[str, ...] | None = None, *, importateur=None) -> dict:
    """BLOQUANT : les modules CRITIQUES doivent s'importer (interpreteur/deps fonctionnels). Par defaut
    des essentiels stdlib qui prouvent que le Python embarque tourne ; l'appelant peut passer la liste
    complete des deps (fastapi, numpy...). `importateur` injectable pour test."""
    import importlib
    imp = importateur or importlib.import_module
    mods = modules if modules is not None else CRITIQUES_STDLIB
    echoues: list[str] = []
    for m in mods:
        try:
            imp(m)
        except Exception:  # noqa: BLE001
            echoues.append(m)
    if echoues:
        return _res("imports", ECHEC, "modules critiques non importables : %s" % ", ".join(echoues))
    return _res("imports", OK, "%d module(s) critique(s) importes" % len(mods))


def verifier_dll(root: str | Path, *, systeme: str | None = None, dossier_python: str | Path | None = None) -> dict:
    """Sur Windows : le Python embarque doit fournir ses DLL (python*.dll). Hors Windows = INFO."""
    systeme = systeme if systeme is not None else platform.system()
    if systeme != "Windows":
        return _res("dll", INFO, "verif DLL propre a Windows (ici %s)" % systeme)
    root = Path(root)
    candidats = [Path(dossier_python)] if dossier_python else [root / "tools" / "python",
                                                               root / "portable_runtime" / "python"]
    for d in candidats:
        if d.is_dir():
            dlls = list(d.glob("python*.dll"))
            if dlls:
                return _res("dll", OK, "DLL Python embarquees presentes (%d)" % len(dlls))
            return _res("dll", ECHEC, "Python embarque sans python*.dll dans %s" % d)
    return _res("dll", AVERT, "aucun Python embarque trouve (repli systeme ?)")


def verifier_manifeste(root: str | Path) -> dict:
    """Integrite du manifeste portable s'il existe (PORTABLE_MANIFEST.json ou runtime portable). Present
    mais corrompu = ECHEC ; absent = INFO (un dossier non encore prepare reste analysable)."""
    root = Path(root)
    for rel in ("PORTABLE_MANIFEST.json",
                "portable_runtime/portable_runtime_manifest.json",
                "tools/python/portable_runtime_manifest.json"):
        p = root / rel
        if p.is_file():
            try:
                m = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                return _res("manifeste", ECHEC, "manifeste %s illisible : %s" % (rel, exc))
            if not isinstance(m, dict) or not (m.get("schema") or m.get("python_version")
                                               or m.get("empreinte_globale")):
                return _res("manifeste", ECHEC, "manifeste %s sans champ d'integrite" % rel)
            return _res("manifeste", OK, "manifeste %s valide" % rel)
    return _res("manifeste", INFO, "aucun manifeste portable (dossier non encore prepare)")


# ── ACTION : regeneration de l'identite machine ───────────────────────────────────────────────
def regenerer_identite(root: str | Path, *, generateur: Callable[[], str] | None = None) -> dict:
    """item 21 : purge l'identite machine-specifique qu'une archive copiee aurait pu conserver
    (registre PID, verrous, marqueur anti-orphelin, pointeur COURANTE) et ecrit un machine-id NEUF.
    Ne touche JAMAIS aux sessions/DATA (historique preserve). Rend la liste de ce qui a ete purge."""
    root = Path(root)
    generateur = generateur or (lambda: uuid.uuid4().hex)
    purges: list[str] = []
    cibles = [REGISTRE_RELPATH,
              Path("runtime") / "data" / "lanceur_session_marqueur.txt",
              Path("runtime") / "data" / "COURANTE.json"]
    for rel in cibles:
        p = root / rel
        if p.is_file():
            try:
                p.unlink()
                purges.append(rel.as_posix())
            except OSError:
                pass
    for lock in list(root.rglob("*.lock")):                # verrous perimes herites d'une copie de dossier
        if lock.name == LOCK_INSTANCE_VIVANT:              # notre verrou vivant : jamais (TTL le gere)
            continue
        if any(part in (".git",) for part in lock.relative_to(root).parts):
            continue
        try:
            lock.unlink()
            purges.append(lock.relative_to(root).as_posix())
        except OSError:
            pass
    # item 6 : dumps de STATUT volatils machine-specifiques (chemins absolus de l'ancien PC).
    for motif in ("runtime/debug_status*.json", "runtime/debug_fusion_status*.json"):
        for p in root.glob(motif):
            try:
                p.unlink()
                purges.append(p.relative_to(root).as_posix())
            except OSError:
                pass
    # item 6 : caches compiles (__pycache__) — propres a une version/chemin, jamais transportes.
    n_caches = 0
    for pc in list(root.rglob("__pycache__")):
        if ".git" in pc.parts:
            continue
        try:
            import shutil as _sh
            _sh.rmtree(pc, ignore_errors=True)
            n_caches += 1
        except OSError:
            pass
    if n_caches:
        purges.append("__pycache__ x%d" % n_caches)
    # item 6 : tache planifiee heritee (chemin absolu de l'ancien PC) — seulement sur Windows.
    if platform.system() == "Windows":
        try:
            import subprocess
            r = subprocess.run(["schtasks", "/Delete", "/TN", "HyperSmart_VerifOOS", "/F"],
                               capture_output=True, timeout=15)
            if r.returncode == 0:
                purges.append("schtasks:HyperSmart_VerifOOS")
        except Exception:  # noqa: BLE001 — absence de tache = rien a purger
            pass
    mid = generateur()
    mp = root / MACHINE_ID_RELPATH
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(mid, encoding="utf-8")
    return {"machine_id": mid, "purges": sorted(purges)}


# ── ORCHESTRATEUR ─────────────────────────────────────────────────────────────────────────────
def verifier_premier_lancement(root: str | Path, *, os_info: dict | None = None,
                               maintenant_ms: float | None = None,
                               sonde_port: Callable[[int], bool] | None = None,
                               sonde_reseau: Callable[[], dict] | None = None,
                               generateur_id: Callable[[], str] | None = None,
                               importateur_imports=None, dossier_python: str | Path | None = None,
                               regenerer: bool = True) -> dict:
    """Enchaine les controles + (option) la regeneration d'identite. GO seulement si AUCUN ECHEC
    bloquant. Les AVERTISSEMENT n'empechent pas le GO (l'analyse marche, la collecte s'adaptera)."""
    root = Path(root)
    oi = os_info or {}
    checks = [
        verifier_os_arch(systeme=oi.get("systeme"), machine=oi.get("machine"), version=oi.get("version")),
        verifier_droits_ecriture(root),
        verifier_espace_disque(root),                          # item 10
        verifier_chemin_espaces_accents(root),
        verifier_horloge(maintenant_ms=maintenant_ms),
        verifier_port(sonde=sonde_port),
        verifier_reseau_tls(sonde=sonde_reseau),
        verifier_imports(importateur=importateur_imports),     # item 10 (BLOQUANT)
        verifier_dll(root, systeme=oi.get("systeme"), dossier_python=dossier_python),  # item 10
        verifier_manifeste(root),                              # item 10
        verifier_aucune_cle(root),
        verifier_sessions_preservees(root),
    ]
    action = regenerer_identite(root, generateur=generateur_id) if regenerer else {}
    echecs = [c for c in checks if c["statut"] == ECHEC]
    avert = [c for c in checks if c["statut"] == AVERT]
    return {"go": not echecs, "echecs": [c["nom"] for c in echecs],
            "avertissements": [c["nom"] for c in avert], "checks": checks,
            "identite": action, "machine_id": action.get("machine_id", "")}


def formater(verdict: dict) -> str:
    lignes = ["PREMIER LANCEMENT : %s" % ("GO" if verdict["go"] else "NO_GO")]
    sym = {OK: "  [OK]  ", INFO: " [INFO] ", AVERT: "[AVERT] ", ECHEC: "[ECHEC] "}
    for c in verdict["checks"]:
        lignes.append("%s%-16s %s" % (sym.get(c["statut"], "  "), c["nom"], c["detail"]))
    if verdict.get("identite"):
        idn = verdict["identite"]
        lignes.append("  [ID]  machine-id neuf=%s ; purges=%s"
                      % (idn.get("machine_id", "")[:8], ", ".join(idn.get("purges", [])) or "aucune"))
    return "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="premier_lancement",
                                 description="Controles de premier lancement HyperSmart (item 21).")
    ap.add_argument("--racine", default=".", help="racine du projet (defaut: dossier courant)")
    ap.add_argument("--sans-regen", action="store_true", help="ne pas regenerer l'identite (diagnostic seul)")
    ap.add_argument("--json", action="store_true", help="sortie JSON")
    args = ap.parse_args(argv)
    verdict = verifier_premier_lancement(Path(args.racine).resolve(), regenerer=not args.sans_regen)
    if args.json:
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
    else:
        print(formater(verdict))
    return 0 if verdict["go"] else 7


__all__ = ["OK", "INFO", "AVERT", "ECHEC", "PORT_UI", "MACHINE_ID_RELPATH", "CRITIQUES_STDLIB",
           "verifier_os_arch", "verifier_droits_ecriture", "verifier_espace_disque",
           "verifier_chemin_espaces_accents", "verifier_horloge", "verifier_port", "verifier_reseau_tls",
           "verifier_imports", "verifier_dll", "verifier_manifeste", "verifier_aucune_cle",
           "verifier_sessions_preservees", "regenerer_identite", "verifier_premier_lancement",
           "formater", "main"]


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
