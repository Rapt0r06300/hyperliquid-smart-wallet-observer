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
import hashlib
import os
import platform
import shutil
import socket
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from hl_observer.ops import session_catalog as SC
from hl_observer.ops.registre_pids import REGISTRE_RELPATH

OK, INFO, AVERT, ECHEC = "OK", "INFO", "AVERTISSEMENT", "ECHEC"
PORT_UI = 8794
MAX_WINDOWS_PATH = 259
MACHINE_ID_RELPATH = Path("runtime") / "data" / "machine_id.txt"
PORTABLE_HOST_STATE_RELPATH = Path("runtime") / "data" / "portable_host_identity.json"
# Le verrou d'instance du lanceur COURANT est VIVANT quand ce module tourne (le .cmd acquiert le
# verrou AVANT le prevol) : ne JAMAIS le purger, sinon un 2e double-clic passerait le garde anti-double
# lancement. Sa peremption est geree par son propre TTL (collection.verrou_instance), pas ici.
LOCK_INSTANCE_VIVANT = "lanceur_instance.lock"
DERIVE_HORLOGE_MAX_MS = 5 * 365 * 24 * 3600 * 1000     # 5 ans : derive « absurde » (pile morte, RTC faux)
# matiere de cle qui ne doit JAMAIS avoir ete copiee (meme paper-strict) — voir archive_portable.
_SUFFIXES_SECRETS = (".key", ".pem", ".p12", ".pfx", ".mnemonic", ".seed", ".keystore")
# [2026-08-05] Dossiers JAMAIS parcourus : caches et metadonnees, aucun secret du projet n'y vit
# et les traverser coutait des secondes a chaque prevol.
_DOSSIERS_NON_PARCOURUS = (".git", "__pycache__", ".mypy_cache", ".ruff_cache", ".pytest_cache",
                           ".hypothesis", "node_modules", ".venv", "venv",
                           # Miroirs tiers archives pour recherche uniquement. Ils ne sont jamais
                           # importes ni executes par le runtime officiel et contiennent leurs
                           # propres fixtures `.env.*`. Les scanner ici bloquerait le CORE sur du
                           # materiel inactif ; les audits d'archive/securite les traitent separement.
                           "github_repos_v24")
# [2026-08-05] EXCEPTIONS NOMMEES, jamais silencieuses (elles sont listees dans le detail du verdict).
# Elles corrigent deux FAUX POSITIFS qui bloquaient le demarrage sans aucun gain de securite :
#   - `cacert.pem` = magasin d'autorites de certification PUBLIQUES livre par certifi (et par pip).
#     Le runtime portable tools\python en contient 2 : c'est de la confiance publique, pas notre cle.
#   - `.env.example` / `.sample` / `.template` / `.dist` = gabarits versionnes SANS secret.
# Tout le reste (`.env` reel, `*.key`, `*.pem` prive, `*.seed`...) reste BLOQUANT, ou qu'il soit.
_FICHIERS_PUBLICS_CONNUS = ("cacert.pem",)
_SUFFIXES_GABARIT = (".example", ".sample", ".template", ".dist")
# [2026-08-10] Chemins relatifs EXACTS de certificats publics tiers (CA bundles) qui ne sont PAS
# des cles privees. Whitelistes par CHEMIN, pas par nom : un `cert.pem` ailleurs reste suspect.
_CHEMINS_PUBLICS_EXACTS = frozenset({
    "tools/git/mingw64/etc/ssl/cert.pem",
})


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


def verifier_longueur_chemins(root: str | Path, *, limite: int = MAX_WINDOWS_PATH) -> dict:
    """Fail closed when the actual target contains a path Windows cannot reliably reopen."""
    racine = Path(root).resolve()
    longueur = len(str(racine))
    membre = "."
    for dossier, sous_dossiers, fichiers in os.walk(racine, topdown=True, followlinks=False):
        courant = Path(dossier)
        for nom in tuple(sous_dossiers) + tuple(fichiers):
            chemin = courant / nom
            valeur = len(str(chemin.absolute()))
            if valeur > longueur:
                longueur = valeur
                try:
                    membre = chemin.relative_to(racine).as_posix()
                except ValueError:
                    membre = str(chemin)
    if longueur > limite:
        return _res(
            "longueur_chemins",
            ECHEC,
            "%d caracteres > %d (%s) ; deplacer vers C:\\HyperSmart" % (longueur, limite, membre),
        )
    return _res("longueur_chemins", OK, "%d/%d caracteres (%s)" % (longueur, limite, membre))


def verifier_outils_windows(
    *,
    systeme: str | None = None,
    which: Callable[[str], str | None] | None = None,
    runner: Callable[..., Any] | None = None,
) -> dict:
    """Prove the Windows control-plane commands required by the launcher."""
    systeme = systeme if systeme is not None else platform.system()
    if systeme != "Windows":
        return _res("outils_windows", INFO, "PowerShell/CIM/taskkill/schtasks controles sur la cible Windows")
    which = which or shutil.which
    requis = ("powershell.exe", "taskkill.exe", "schtasks.exe")
    absents = tuple(nom for nom in requis if not which(nom))
    if absents:
        return _res("outils_windows", ECHEC, "outils Windows absents : " + ", ".join(absents))
    runner = runner or subprocess.run
    try:
        resultat = runner(
            [which("powershell.exe") or "powershell.exe", "-NoProfile", "-Command", "Get-Command Get-CimInstance | Out-Null"],
            check=False,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return _res("outils_windows", ECHEC, "preuve PowerShell/CIM impossible : %s" % exc)
    if int(getattr(resultat, "returncode", 1)) != 0:
        return _res("outils_windows", ECHEC, "PowerShell present mais Get-CimInstance indisponible")
    return _res("outils_windows", OK, "PowerShell + CIM + taskkill + schtasks disponibles")


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


def _est_suspect(nom: str) -> bool:
    """Nom de fichier (deja en minuscules) qui porte de la matiere de cle potentielle."""
    return (nom == ".env" or nom.startswith(".env.")
            or any(nom.endswith(sfx) for sfx in _SUFFIXES_SECRETS))


def _est_publiquement_connu(nom: str, rel: str = "") -> bool:
    """Faux positif NOMME : magasin d'autorites publiques, chemin public exact, ou gabarit sans secret."""
    if nom in _FICHIERS_PUBLICS_CONNUS:
        return True
    if rel and rel in _CHEMINS_PUBLICS_EXACTS:
        return True
    return any(nom.endswith(s) for s in _SUFFIXES_GABARIT)


def verifier_aucune_cle(root: str | Path) -> dict:
    """BLOQUANT : aucune matiere de cle ne doit avoir ete copiee (extension, pas sous-chaine).

    [2026-08-05] Deux faux positifs rendaient ce controle TOUJOURS bloquant, donc le lanceur
    TOUJOURS NO_GO : `.env.example` (gabarit versionne) et les `cacert.pem` de certifi embarques
    dans le runtime portable. Ils sont desormais reconnus, COMPTES et AFFICHES dans le verdict —
    jamais masques. Aucun autre assouplissement : un vrai `.env`, un `*.key`, un `*.pem` prive
    bloquent toujours, partout.
    """
    root = Path(root)
    trouves: list[str] = []
    connus: list[str] = []
    for dossier, sous_dossiers, fichiers in os.walk(root):
        sous_dossiers[:] = [d for d in sous_dossiers if d not in _DOSSIERS_NON_PARCOURUS]
        base = Path(dossier)
        rel_dir = "" if base == root else base.relative_to(root).as_posix()
        for fichier in fichiers:
            nom = fichier.lower()
            if not _est_suspect(nom):
                continue
            rel = "%s/%s" % (rel_dir, fichier) if rel_dir else fichier
            if _est_publiquement_connu(nom, rel):
                if len(connus) < 20:
                    connus.append(rel)
                continue
            trouves.append(rel)
            if len(trouves) >= 20:
                break
        if len(trouves) >= 20:
            break
    if trouves:
        return _res("aucune_cle", ECHEC, "matiere de cle presente (a retirer) : %s" % ", ".join(trouves))
    if connus:
        return _res("aucune_cle", OK, "aucune matiere de cle du projet ; %d fichier(s) public(s)/gabarit "
                    "reconnu(s) : %s" % (len(connus), ", ".join(connus)))
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
                # PowerShell 5.1 peut produire un JSON UTF-8 avec BOM. `utf-8-sig`
                # accepte les deux formes sans masquer un JSON reellement corrompu.
                m = json.loads(p.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError) as exc:
                return _res("manifeste", ECHEC, "manifeste %s illisible : %s" % (rel, exc))
            if not isinstance(m, dict) or not (m.get("schema") or m.get("python_version")
                                               or m.get("empreinte_globale")):
                return _res("manifeste", ECHEC, "manifeste %s sans champ d'integrite" % rel)
            return _res("manifeste", OK, "manifeste %s valide" % rel)
    return _res("manifeste", INFO, "aucun manifeste portable (dossier non encore prepare)")


# ── item 4 : deps tierces REELLES + modules runtime + arch des wheels + certificats TLS ────────
# CORE = indispensables a l'UI/API, aux collecteurs et aux donnees. OPTIONNELLES = recherche (l'analyse
# tourne sans, mais on le SIGNALE honnêtement). Absente en CORE = ECHEC ; en optionnelle = AVERT.
DEPS_CORE = ("fastapi", "httpx", "pydantic", "sqlalchemy", "uvicorn", "websocket", "websockets",
             "yaml", "psutil", "rich", "requests", "numpy", "scipy", "pandas")
DEPS_OPTIONNELLES = ("aiohttp", "lz4", "optuna", "cmaes")
# Modules runtime REELLEMENT utilises (UI/moteur/collecteurs/analyse) — prouve que le paquet se charge.
MODULES_RUNTIME = ("hl_observer.ops.session_catalog", "hl_observer.ops.session_harvest",
                   "hl_observer.ops.analyser_session", "hl_observer.ops.archive_portable",
                   "hl_observer.ops.lab_flux", "hl_observer.normalization.market_events",
                   "hl_observer.collection.tick_dataset", "hl_observer.market_truth.pipeline",
                   "hl_observer.paper_trading", "hl_observer.edge.edge_calculator")


def verifier_deps_tierces(*, core: tuple[str, ...] | None = None,
                          optionnelles: tuple[str, ...] | None = None, importateur=None) -> dict:
    """BLOQUANT sur les deps CORE (fastapi/numpy/...). Les optionnelles manquantes = AVERT (recherche
    degradee, honnete). Importe REELLEMENT chaque paquet — pas seulement la stdlib (item 4)."""
    import importlib
    imp = importateur or importlib.import_module
    core = core if core is not None else DEPS_CORE
    opt = optionnelles if optionnelles is not None else DEPS_OPTIONNELLES
    manque_core = [m for m in core if not _importe(imp, m)]
    manque_opt = [m for m in opt if not _importe(imp, m)]
    if manque_core:
        return _res("deps_tierces", ECHEC, "deps CORE absentes : %s" % ", ".join(manque_core))
    if manque_opt:
        return _res("deps_tierces", AVERT, "deps recherche absentes (analyse OK) : %s" % ", ".join(manque_opt))
    return _res("deps_tierces", OK, "%d deps CORE + %d optionnelles importees" % (len(core), len(opt)))


def verifier_modules_runtime(*, modules: tuple[str, ...] | None = None, importateur=None) -> dict:
    """BLOQUANT : les modules runtime reellement utilises doivent s'importer (le paquet se charge)."""
    import importlib
    imp = importateur or importlib.import_module
    mods = modules if modules is not None else MODULES_RUNTIME
    manque = [m for m in mods if not _importe(imp, m)]
    if manque:
        return _res("modules_runtime", ECHEC, "modules runtime non importables : %s" % ", ".join(manque))
    return _res("modules_runtime", OK, "%d modules runtime importes" % len(mods))


def _importe(imp, nom: str) -> bool:
    try:
        imp(nom)
        return True
    except Exception:  # noqa: BLE001
        return False


def verifier_wheels_arch(root: str | Path, *, arch: str = "win_amd64", pytag: str = "cp311") -> dict:
    """item 4 : dans le wheelhouse, chaque roue doit etre soit pure (`*-none-any.whl`) soit de la bonne
    plateforme (`*win_amd64*`). Une roue d'une autre arch/ABI = INCOMPATIBLE -> ECHEC. Absent = INFO."""
    wh = Path(root) / "tools" / "wheelhouse"
    if not wh.is_dir():
        return _res("wheels_arch", INFO, "pas de wheelhouse (dossier non encore prepare)")
    roues = list(wh.glob("*.whl"))
    if not roues:
        return _res("wheels_arch", INFO, "wheelhouse vide")
    incompatibles = []
    for w in roues:
        bas = w.name.lower()
        if bas.endswith("-none-any.whl"):
            continue                                       # pure python : compatible partout
        if arch in bas:
            continue                                       # bonne plateforme
        incompatibles.append(w.name)
    if incompatibles:
        return _res("wheels_arch", ECHEC, "roues d'arch incompatible (%s attendu) : %s"
                    % (arch, ", ".join(incompatibles[:5])))
    return _res("wheels_arch", OK, "%d roue(s) toutes compatibles %s" % (len(roues), arch))


def verifier_certificats_tls() -> dict:
    """AVERT si aucune autorite de certification n'est chargeable (collecte HTTPS impossible). L'analyse
    hors-ligne n'en a pas besoin -> jamais bloquant."""
    import ssl
    try:
        ctx = ssl.create_default_context()
        n = len(ctx.get_ca_certs())
    except Exception as exc:  # noqa: BLE001
        return _res("tls_ca", AVERT, "contexte TLS indisponible : %s" % exc)
    if n <= 0:
        try:
            import certifi  # type: ignore
            if Path(certifi.where()).is_file():
                return _res("tls_ca", OK, "CA via certifi")
        except Exception:  # noqa: BLE001
            import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
            _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
        return _res("tls_ca", AVERT, "aucune autorite de certification chargee (collecte HTTPS a verifier)")
    return _res("tls_ca", OK, "%d autorites de certification chargees" % n)


# ── ACTION : regeneration de l'identite machine ───────────────────────────────────────────────
def _empreinte(valeur: str) -> str:
    return hashlib.sha256(valeur.encode("utf-8", errors="replace")).hexdigest()


def _identite_hote() -> str:
    """Return a stable host token; only its hash is persisted in the project."""
    morceaux = [platform.node(), platform.machine(), os.environ.get("COMPUTERNAME", "")]
    if platform.system() == "Windows":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography"
            ) as cle:
                guid, _ = winreg.QueryValueEx(cle, "MachineGuid")
                morceaux.append(str(guid))
        except (OSError, ImportError):
            pass
    return "|".join(morceaux)


def _iter_verrous_machine(root: Path):
    """Inspect only small machine-state trees, never datasets or embedded runtimes."""
    vus: set[Path] = set()
    for lock in root.glob("*.lock"):
        if lock.is_file():
            vus.add(lock)
            yield lock
    for rel in (
        Path("runtime") / "data",
        Path("runtime") / "research_lab" / "heartbeats",
        Path("runtime") / "ws",
        Path("data") / "runtime",
        Path("logs"),
    ):
        base = root / rel
        if not base.is_dir():
            continue
        for lock in base.rglob("*.lock"):
            if lock.is_file() and lock not in vus:
                vus.add(lock)
                yield lock


def _iter_caches_source(root: Path):
    """Yield project bytecode caches without walking the 160 GB data/runtime trees."""
    direct = root / "__pycache__"
    if direct.is_dir():
        yield direct
    for top in (root / "src", root / "hyper_smart_observer", root / "tools"):
        if not top.is_dir():
            continue
        for dossier, sous_dossiers, _ in os.walk(top, topdown=True):
            sous_dossiers[:] = [
                nom
                for nom in sous_dossiers
                if nom.casefold()
                not in {"python", "wheelhouse", "github_repos_v24", ".git"}
            ]
            courant = Path(dossier)
            if courant.name == "__pycache__":
                sous_dossiers[:] = []
                yield courant


def regenerer_identite(
    root: str | Path,
    *,
    generateur: Callable[[], str] | None = None,
    preserve_instance_lock: bool = True,
    nettoyer_caches: bool = True,
) -> dict:
    """item 21 : purge l'identite machine-specifique qu'une archive copiee aurait pu conserver
    (registre PID, verrous, marqueur anti-orphelin, pointeur COURANTE) et ecrit un machine-id NEUF.
    Ne touche JAMAIS aux sessions/DATA (historique preserve). Rend la liste de ce qui a ete purge."""
    root = Path(root)
    generateur = generateur or (lambda: uuid.uuid4().hex)
    purges: list[str] = []
    cibles = [REGISTRE_RELPATH,
              Path("runtime") / "data" / "lanceur_session_marqueur.txt",
              Path("runtime") / "data" / "COURANTE.json",
              Path("runtime") / "data" / "sessions" / "COURANTE.json"]
    for rel in cibles:
        p = root / rel
        if p.is_file():
            try:
                p.unlink()
                purges.append(rel.as_posix())
            except OSError:
                import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
                _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
    for lock in list(_iter_verrous_machine(root)):
        if preserve_instance_lock and lock.name == LOCK_INSTANCE_VIVANT:
            continue
        try:
            lock.unlink()
            purges.append(lock.relative_to(root).as_posix())
        except OSError:
            import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
            _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
    # item 6 : dumps de STATUT volatils machine-specifiques (chemins absolus de l'ancien PC).
    for motif in ("runtime/debug_status*.json", "runtime/debug_fusion_status*.json"):
        for p in root.glob(motif):
            try:
                p.unlink()
                purges.append(p.relative_to(root).as_posix())
            except OSError:
                import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
                _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
    # item 6 : caches compiles (__pycache__) — propres a une version/chemin, jamais transportes.
    if nettoyer_caches:
        n_caches = 0
        for pc in list(_iter_caches_source(root)):
            try:
                import shutil as _sh
                _sh.rmtree(pc, ignore_errors=True)
                n_caches += 1
            except OSError:
                import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
                _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
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
            import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
            _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
    mid = generateur()
    mp = root / MACHINE_ID_RELPATH
    mp.parent.mkdir(parents=True, exist_ok=True)
    mp.write_text(mid, encoding="utf-8")
    return {"machine_id": mid, "purges": sorted(purges)}


def preparer_identite_portable(
    root: str | Path,
    *,
    generateur: Callable[[], str] | None = None,
    identite_hote: str | None = None,
    force: bool = False,
) -> dict:
    """Regenerate machine state once, and only after a real folder relocation.

    The persisted file contains hashes only. A routine launch on the same host and
    path is therefore non-destructive and does not touch PIDs, locks or sessions.
    """
    root = Path(root).resolve()
    etat_path = root / PORTABLE_HOST_STATE_RELPATH
    host_fp = _empreinte(identite_hote if identite_hote is not None else _identite_hote())
    root_fp = _empreinte(os.path.normcase(str(root)))
    ancien: dict[str, Any] = {}
    if etat_path.is_file():
        try:
            charge = json.loads(etat_path.read_text(encoding="utf-8-sig"))
            if isinstance(charge, dict):
                ancien = charge
        except (OSError, json.JSONDecodeError):
            ancien = {}

    raisons: list[str] = []
    if force:
        raisons.append("FORCE")
    if not ancien:
        raisons.append("FIRST_START_OR_LEGACY_COPY")
    else:
        if ancien.get("host_fingerprint") != host_fp:
            raisons.append("HOST_CHANGED")
        if ancien.get("root_fingerprint") != root_fp:
            raisons.append("ROOT_CHANGED")
        if not (root / MACHINE_ID_RELPATH).is_file():
            raisons.append("MACHINE_ID_MISSING")

    if not raisons:
        return {
            "changed": False,
            "reason": "SAME_HOST_AND_ROOT",
            "machine_id": (root / MACHINE_ID_RELPATH).read_text(
                encoding="utf-8-sig", errors="replace"
            ).strip(),
            "purges": [],
        }

    action = regenerer_identite(
        root,
        generateur=generateur,
        preserve_instance_lock=False,
        nettoyer_caches=False,
    )
    etat_path.parent.mkdir(parents=True, exist_ok=True)
    etat_path.write_text(
        json.dumps(
            {
                "schema": "hypersmart-portable-host-identity-v1",
                "host_fingerprint": host_fp,
                "root_fingerprint": root_fp,
                "machine_id": action["machine_id"],
                "updated_at_ms": int(time.time() * 1000),
            },
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        **action,
        "changed": True,
        "reason": "+".join(raisons),
    }


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
        verifier_longueur_chemins(root),
        verifier_outils_windows(systeme=oi.get("systeme")),
        verifier_horloge(maintenant_ms=maintenant_ms),
        verifier_port(sonde=sonde_port),
        verifier_reseau_tls(sonde=sonde_reseau),
        verifier_imports(importateur=importateur_imports),     # item 10 (stdlib essentiels, BLOQUANT)
        verifier_deps_tierces(importateur=importateur_imports),  # item 4 (deps CORE reelles, BLOQUANT)
        verifier_modules_runtime(importateur=importateur_imports),  # item 4 (modules runtime, BLOQUANT)
        verifier_dll(root, systeme=oi.get("systeme"), dossier_python=dossier_python),  # item 10
        verifier_wheels_arch(root),                            # item 4 (arch des wheels)
        verifier_certificats_tls(),                            # item 4 (CA TLS)
        verifier_manifeste(root),                              # item 10
        verifier_aucune_cle(root),
        verifier_sessions_preservees(root),
    ]
    echecs = [c for c in checks if c["statut"] == ECHEC]
    avert = [c for c in checks if c["statut"] == AVERT]
    action = (
        preparer_identite_portable(root, generateur=generateur_id)
        if regenerer and not echecs
        else {}
    )
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
        lignes.append("  [ID]  %s ; machine-id=%s ; purges=%s"
                      % (idn.get("reason", "UNKNOWN"), idn.get("machine_id", "")[:8],
                         ", ".join(idn.get("purges", [])) or "aucune"))
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
           "DEPS_CORE", "DEPS_OPTIONNELLES", "MODULES_RUNTIME",
           "verifier_os_arch", "verifier_droits_ecriture", "verifier_espace_disque",
           "verifier_chemin_espaces_accents", "verifier_longueur_chemins", "verifier_outils_windows",
           "verifier_horloge", "verifier_port", "verifier_reseau_tls",
           "verifier_imports", "verifier_deps_tierces", "verifier_modules_runtime", "verifier_dll",
           "verifier_wheels_arch", "verifier_certificats_tls", "verifier_manifeste", "verifier_aucune_cle",
           "verifier_sessions_preservees", "regenerer_identite", "preparer_identite_portable",
           "verifier_premier_lancement", "PORTABLE_HOST_STATE_RELPATH",
           "formater", "main"]


if __name__ == "__main__":                              # pragma: no cover
    raise SystemExit(main())
