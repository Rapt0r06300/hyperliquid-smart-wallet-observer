"""SUPERVISEUR DES COLLECTEURS — constater une panne ne suffit pas, il faut RELANCER.

CE QUI S'EST PASSÉ LE 19/07 (la panne qui a affamé le bot)
----------------------------------------------------------
À 15:27, les quatre collecteurs (carry-feeder, marks, liquidations, venues) sont morts
dans la même fenêtre de 35 secondes — chacun proprement, en plein sommeil, dernier log
« code de sortie = 0 ». Quinze minutes plus tard, `carry_spot_inputs.json` était périmé
(> 900 s), et le carry s'est mis à refuser chaque évaluation : `INPUTS_SPOT_PERIMES_NO_TRADE`,
indéfiniment. Le refus était CORRECT — c'est l'alimentation qui était morte.

On avait déjà l'ALARME (`VERIFIER-TOUT.cmd`, section 5 : « log figé depuis N min »). Mais une
alarme que personne ne regarde pendant que le bot tourne ne relance rien. C'est la maladie du
projet transposée à l'exploitation : capacité présente, chaînon manquant, personne ne se plaint.
Ce module est le chaînon : le moteur (qui, LUI, survit — prouvé le 19/07) constate le silence
d'un collecteur et le relance.

RÈGLES
------
* JAMAIS d'exception vers l'appelant : un superviseur qui fait tomber le moteur qu'il protège
  serait pire que la panne.
* COOLDOWN par collecteur (10 min) : si la relance échoue, on ne mitraille pas — un collecteur
  qui remeurt en boucle est un symptôme à diagnostiquer, pas à masquer sous des relances.
* Chaque relance est JOURNALISÉE (`runtime/data/superviseur_collecteurs.json`) : un processus
  ressuscité en silence serait un mensonge de plus.
* Relance réelle sous Windows uniquement (le runtime vit là-bas) ; ailleurs (sandbox), le
  lanceur par défaut refuse poliment — les tests injectent le leur.

Sécurité : les collecteurs sont en LECTURE SEULE sur des endpoints publics.
0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import json
import os
import subprocess  # noqa: S404 — relance de NOS scripts locaux, chemins codés en dur
import time
from pathlib import Path
from typing import Any, Callable

#: Interrupteur. Par défaut ON : un bot qui se laisse affamer sans réagir n'observe plus rien.
ENV_INTERRUPTEUR = "HYPERSMART_SUPERVISEUR_COLLECTEURS"

#: Une relance par collecteur toutes les 10 min AU PLUS. Assez court pour réparer vite,
#: assez long pour qu'une panne récurrente reste VISIBLE dans le journal au lieu de clignoter.
COOLDOWN_S = 600.0

JOURNAL_RELPATH = Path("runtime") / "data" / "superviseur_collecteurs.json"

#: Compteur des pannes INTERNES du superviseur (journal inecrivable, noter indisponible).
#: Cliquet « 105 -> 0 except:pass » : on peut avaler une erreur, JAMAIS sans laisser de piste.
#: Un dict module-level suffit : il se lit au debugger et dans les tests, et ne leve jamais.
PANNES_INTERNES: dict[str, int] = {}


def _compter_panne_interne(site: str) -> None:
    PANNES_INTERNES[site] = PANNES_INTERNES.get(site, 0) + 1

from hl_observer.ops.collecteur_registry import (
    COLLECTEURS_CAMPAGNE,
    COLLECTEURS_CORE,
    COLLECTEURS_HARVEST,
    COLLECTEURS_MAINTENANCE,
    COLLECTEURS_REQUIS,
    COLLECTEURS_RESEARCH,
    PROFILS_VALIDES,
    REGISTRE,
    collecteurs_pour_profil,
    collecteurs_requis_pour_run,
    experimental_paper_demande,
    normaliser_profil,
    profil_collecteur,
)

def actif() -> bool:
    return os.environ.get(ENV_INTERRUPTEUR, "1").strip() not in {"0", "false", "non", "off"}


def age_log_minutes(root: Path, nom: str, *, maintenant: float | None = None) -> float | None:
    """None = le log n'existe pas (collecteur jamais démarré — mort aussi, autrement)."""
    p = Path(root) / "runtime" / "logs" / ("%s.log" % nom)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        return None
    return ((maintenant if maintenant is not None else time.time()) - mtime) / 60.0


def age_vie_minutes(root: Path, c: dict[str, Any], *, maintenant: float | None = None) -> float | None:
    """Âge de la DERNIÈRE PREUVE DE VIE. Pour un collecteur PERSISTANT (clé `heartbeat`), c'est la fraîcheur
    de son fichier heartbeat (il écrit la DATA en continu, jamais un log par seconde) ; sinon la fraîcheur du
    log. Corrige le FAUX STALL de bbo/userfills (vivants mais log figé) et empêche le watchdog de les dupliquer."""
    hb = c.get("heartbeat")
    if hb:
        try:
            mt = (Path(root) / hb).stat().st_mtime
            return ((maintenant if maintenant is not None else time.time()) - mt) / 60.0
        except OSError:
            import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
            _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
    return age_log_minutes(root, c["nom"], maintenant=maintenant)


def etat_collecteurs(
    root: Path,
    *,
    maintenant: float | None = None,
    profil: str = "all",
) -> list[dict[str, Any]]:
    """Un dict par collecteur du REGISTRE : {nom, age_minutes, limite_minutes, mort}."""
    out: list[dict[str, Any]] = []
    for c in collecteurs_pour_profil(profil):
        age = age_vie_minutes(root, c, maintenant=maintenant)
        out.append({
            "nom": c["nom"],
            "profil": profil_collecteur(c["nom"]),
            "age_minutes": None if age is None else round(age, 1),
            "limite_minutes": c["limite_minutes"],
            # log absent = mort (jamais démarré), log figé au-delà de la limite = mort.
            "mort": age is None or age > c["limite_minutes"],
        })
    return out


def _commande_relance(c: dict[str, Any]) -> list[str]:
    """La MÊME ligne que LANCER_HYPERSMART.cmd : chemins RELATIFS, zéro guillemet.
    (Leçon du 19/07 : `cmd /c` mange la première et la dernière quote quand il y a
    plusieurs paires — les chemins absolus quotés avaient cassé 3 lancements de suite.)"""
    script_rel = str(c["script"]).replace("/", "\\")
    return ["cmd", "/c", "start", "", "/b", "tools\\boucle_collecteur.cmd",
            str(c["nom"]), script_rel, str(int(c["intervalle_s"])), *map(str, c["args"])]


def _lanceur_windows(commande: list[str], cwd: Path) -> bool:
    """Relance réelle — Windows uniquement, là où vit le runtime. Ailleurs : refus poli.

    🔴 GARDE AJOUTÉE LE 19/07 (attrapée par l'AUDIT WINDOWS de Flo, popup à l'écran) :
    un appel avec une racine qui n'est pas le vrai repo (test sans lanceur injecté, fuzzing)
    faisait un VRAI `start tools\\boucle_collecteur.cmd` depuis un dossier où ce fichier
    n'existe pas -> boîte de dialogue Windows « ne trouve pas » en plein audit. Sous Linux
    le refus était silencieux, donc mes tests sandbox ne l'ont jamais vu. *La vérité, c'est
    Windows.* On vérifie l'existence du script AVANT de lancer : racine sans boucle = refus.
    """
    if os.name != "nt":
        return False
    if not (Path(cwd) / "tools" / "boucle_collecteur.cmd").is_file():
        return False                      # racine fantaisiste : on ne lance RIEN (et 0 popup)
    try:
        subprocess.Popen(commande, cwd=str(cwd),  # noqa: S603 — nos scripts, chemins fixes
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except OSError:
        return False


def _lire_journal(root: Path) -> dict[str, Any]:
    try:
        d = json.loads((Path(root) / JOURNAL_RELPATH).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _ecrire_journal(root: Path, journal: dict[str, Any]) -> None:
    try:
        chemin = Path(root) / JOURNAL_RELPATH
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(journal, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        # un journal inecrivable n'empeche pas la relance -- mais il est COMPTE (cliquet 105->0)
        _compter_panne_interne("journal_inecrivable")


def _collecteurs_en_panne_semantique(
    root: Path,
    now: float,
    diagnostic: Callable[..., Any] | None = None,
) -> frozenset[str]:
    """Noms des collecteurs dont la PREUVE DE VIE diagnostique une PANNE SÉMANTIQUE : process VIVANT +
    heartbeat FRAIS, mais flux CASSÉ (gap critique / carnet désync / séquence invalide / resync / hors-
    ordre / carnet stale / reconnexions en rafale). RÉUTILISE la détection existante (`preuve_de_vie`,
    qui s'appuie sur `protections.etat_ingestion`) — ne RÉINVENTE aucun diagnostic. Un MARCHÉ CALME
    (0 événement mais collecte OK) reste VERT dans `preuve_de_vie` → jamais classé PANNE_TECHNIQUE →
    jamais retourné ici → jamais relancé (relancer un collecteur sain en marché calme serait la panne
    INVERSE). Ne LÈVE JAMAIS : au moindre doute (diagnostic indisponible), ensemble VIDE — on ne relance
    pas sur une incertitude."""
    try:
        from hl_observer.ops.preuve_de_vie import CAUSE_PANNE_TECHNIQUE, evaluer_depuis_disque
        diag = diagnostic if diagnostic is not None else evaluer_depuis_disque
        etat = diag(root, now_ms=now * 1000.0)
        return frozenset(
            str(c.get("source"))
            for c in (getattr(etat, "causes", ()) or ())
            if isinstance(c, dict) and c.get("cause") == CAUSE_PANNE_TECHNIQUE and c.get("source")
        )
    except Exception:  # noqa: BLE001 — un diagnostic en panne ne doit ni nous tuer ni relancer à tort
        return frozenset()


def verifier_et_relancer(
    root: str | Path,
    *,
    maintenant: float | None = None,
    lanceur: Callable[[list[str], Path], bool] | None = None,
    cooldown_s: float = COOLDOWN_S,
    profil: str = "core",
    diagnostic_semantique: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Une passe de supervision. Retourne un rapport, ne lève JAMAIS.

    Relance un collecteur MORT (silence : heartbeat/log trop vieux) ET un collecteur VIVANT dont la
    preuve de vie diagnostique une PANNE SÉMANTIQUE (heartbeat frais mais flux cassé). Un MARCHÉ CALME
    reste sain : JAMAIS relancé (`preuve_de_vie` le classe VERT, pas PANNE_TECHNIQUE).

    rapport = {actif, morts: [noms], pannes: [noms], relances: [noms], en_cooldown: [noms]}
    """
    try:
        racine = Path(root)
        profil_normalise = normaliser_profil(profil)
        collecteurs = collecteurs_pour_profil(profil_normalise)
        if not actif():
            return {
                "actif": False,
                "profil": profil_normalise,
                "morts": [],
                "pannes": [],
                "relances": [],
                "en_cooldown": [],
            }
        now = maintenant if maintenant is not None else time.time()
        lancer = lanceur if lanceur is not None else _lanceur_windows
        journal = _lire_journal(racine)
        # Panne SÉMANTIQUE (heartbeat FRAIS mais flux cassé) — diagnostiquée par preuve_de_vie, PAS ici.
        # MARCHE_CALME y reste VERT → absent de cet ensemble → jamais relancé (piège du marché calme).
        pannes_semantiques = _collecteurs_en_panne_semantique(racine, now, diagnostic_semantique)
        morts: list[str] = []
        pannes: list[str] = []
        relances: list[str] = []
        en_cooldown: list[str] = []

        for c, etat in zip(
            collecteurs,
            etat_collecteurs(racine, maintenant=now, profil=profil_normalise),
        ):
            est_mort = bool(etat["mort"])
            # VIVANT mais SÉMANTIQUEMENT cassé (gap/désync/…) compte AUSSI comme à relancer. Jamais sur
            # marché calme : pannes_semantiques exclut MARCHE_CALME. Le silence (mort) reste prioritaire.
            est_panne = (not est_mort) and (c["nom"] in pannes_semantiques)
            if not est_mort and not est_panne:
                continue
            (morts if est_mort else pannes).append(c["nom"])
            derniere = journal.get(c["nom"], {}).get("derniere_relance_ts")
            if isinstance(derniere, (int, float)) and (now - derniere) < cooldown_s:
                en_cooldown.append(c["nom"])
                continue
            ok = False
            try:
                ok = bool(lancer(_commande_relance(c), racine))
            except Exception:  # noqa: BLE001 — le lanceur injecté ne doit pas nous tuer
                ok = False
            entree = journal.setdefault(c["nom"], {})
            entree["derniere_relance_ts"] = now
            entree["derniere_relance_ok"] = ok
            entree["relances_total"] = int(entree.get("relances_total") or 0) + 1
            entree["age_minutes_au_constat"] = etat["age_minutes"]
            entree["cause_relance"] = "mort" if est_mort else "panne_semantique"
            if ok:
                relances.append(c["nom"])

        if morts or pannes:
            journal["derniere_passe_ts"] = now
            _ecrire_journal(racine, journal)
        return {"actif": True, "profil": profil_normalise, "morts": morts, "pannes": pannes,
                "relances": relances, "en_cooldown": en_cooldown}
    except Exception as exc:  # noqa: BLE001 — jamais d'exception vers le moteur
        try:
            from hl_observer.ops.echec_silencieux import noter
            noter("superviseur_collecteurs", exc)
        except Exception:  # noqa: BLE001
            # meme le compteur officiel est en panne : on compte LOCALEMENT (jamais muet)
            _compter_panne_interne("noter_indisponible")
        return {"actif": True, "profil": str(profil), "morts": [], "pannes": [], "relances": [],
                "en_cooldown": [], "erreur": str(exc)[:200]}


# ─────────────────────────────────────────────────────────────────────────────────────────────
#  DÉMARRAGE / STATUS / ARRÊT CIBLÉ — pilotés par le MÊME REGISTRE (source unique, 25/07).
#  Le lanceur (cmd) appelle ces fonctions : plus aucune liste de collecteurs dupliquée en .cmd.
# ─────────────────────────────────────────────────────────────────────────────────────────────
PIDS_RELPATH = Path("runtime") / "data" / "collecteurs_pids.json"
PORT_UI = 8794
LOCK_USERFILLS = Path("runtime") / "data" / "userfills_live.lock"


def _ecrire_pids_atomique(root: str | Path, registre: dict[str, Any]) -> bool:
    """Écrit le registre PID des collecteurs de façon ATOMIQUE (AUD-057) : sérialise dans un fichier
    temporaire (flush + fsync) PUIS `os.replace` — JAMAIS un `write_text` direct sur la cible. Un crash en
    cours d'écriture ne peut donc pas laisser un `collecteurs_pids.json` tronqué : l'arrêt CIBLÉ lit toujours
    un JSON complet (comme `registre_pids._ecrire_atomique` le fait déjà pour le registre du lanceur).
    Rend True si l'écriture a abouti, False sinon (l'appelant COMPTE la panne, jamais silencieuse)."""
    cible = Path(root) / PIDS_RELPATH
    texte = json.dumps(registre, ensure_ascii=False, indent=1)
    try:
        cible.parent.mkdir(parents=True, exist_ok=True)
        tmp = cible.with_suffix(cible.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(texte)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, cible)
        return True
    except OSError:
        return False


def commande_collecteur(c: dict[str, Any]) -> list[str]:
    """Commande cmd d'UN collecteur (chemins relatifs, sans guillemets) — PID capturable (pas `start`)."""
    script_rel = str(c["script"]).replace("/", "\\")
    return ["cmd", "/c", "tools\\boucle_collecteur.cmd",
            str(c["nom"]), script_rel, str(int(c["intervalle_s"])), *map(str, c["args"])]


def _spawn_pid(c: dict[str, Any], cwd: Path) -> int | None:
    """Lance UN collecteur DÉTACHÉ (sans fenêtre) et REND SON PID. Windows only ; ailleurs None.
    Vérifie l'existence de boucle_collecteur.cmd (jamais de popup « introuvable »)."""
    if os.name != "nt":
        return None
    if not (Path(cwd) / "tools" / "boucle_collecteur.cmd").is_file():
        return None
    try:
        flags = 0x08000000 | 0x00000200          # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
        p = subprocess.Popen(commande_collecteur(c), cwd=str(cwd),  # noqa: S603 — nos scripts, chemins fixes
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, creationflags=flags)
        return int(p.pid)
    except OSError:
        return None


def _lire_pids(root: str | Path) -> dict[str, Any]:
    try:
        d = json.loads((Path(root) / PIDS_RELPATH).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _pid_collecteur_existant(c: dict[str, Any], procs: list[dict[str, Any]]) -> int | None:
    nom = c["nom"]
    script = str(c["script"]).split("/")[-1]
    for proc in procs:
        ligne = str(proc.get("cmd") or "")
        if ((" %s " % nom) in (" " + ligne + " ")) or script in ligne:
            pid = proc.get("pid")
            if isinstance(pid, int):
                return pid
    return None


def _processus_du_collecteur(
    c: dict[str, Any], procs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return wrapper and worker processes belonging to one collector."""
    nom = str(c["nom"])
    script = str(c["script"]).replace("/", "\\").split("\\")[-1]
    return [
        proc
        for proc in procs
        if ((" %s " % nom) in (" " + str(proc.get("cmd") or "") + " "))
        or script in str(proc.get("cmd") or "")
    ]


def _nombre_instances_logiques(
    c: dict[str, Any], procs: list[dict[str, Any]]
) -> tuple[int, int]:
    """Count collectors without counting a CMD wrapper and its child twice."""
    correspondants = _processus_du_collecteur(c, procs)
    if not correspondants:
        return 0, 0
    nom = str(c["nom"])
    wrappers = {
        int(proc["pid"])
        for proc in correspondants
        if isinstance(proc.get("pid"), int)
        and "boucle_collecteur.cmd" in str(proc.get("cmd") or "").lower()
        and (" %s " % nom) in (" " + str(proc.get("cmd") or "") + " ")
    }
    if wrappers:
        return len(wrappers), len(correspondants)
    pids = {
        int(proc["pid"])
        for proc in correspondants
        if isinstance(proc.get("pid"), int)
    }
    racines = {
        int(proc["pid"])
        for proc in correspondants
        if isinstance(proc.get("pid"), int) and proc.get("ppid") not in pids
    }
    return len(racines or pids), len(correspondants)


def demarrer_tous(
    root: str | Path,
    *,
    run_id: str | None = None,
    spawner: Callable[[dict, Path], int | None] | None = None,
    profil: str = "core",
    procs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Démarre tous les collecteurs du REGISTRE et ENREGISTRE leur PID (base de l'arrêt CIBLÉ).
    Ne lève jamais. Rend {run_id, pids, manquants}."""
    racine = Path(root)
    profil_normalise = normaliser_profil(profil)
    collecteurs = collecteurs_pour_profil(profil_normalise)
    rid = run_id or ("run-" + os.urandom(6).hex())
    lance = spawner if spawner is not None else _spawn_pid
    processus = (
        list(procs)
        if procs is not None
        else (_processus_projet(racine) if spawner is None else [])
    )
    pids: dict[str, int] = {}
    manquants: list[str] = []
    reutilises: list[str] = []
    for c in collecteurs:
        pid_existant = _pid_collecteur_existant(c, processus)
        if pid_existant is not None:
            pids[c["nom"]] = pid_existant
            reutilises.append(c["nom"])
            continue
        try:
            pid = lance(c, racine)
        except Exception:  # noqa: BLE001 — un spawner injecté ne doit pas nous tuer
            pid = None
        if pid:
            pids[c["nom"]] = int(pid)
        else:
            manquants.append(c["nom"])
    # Le fichier PID est commun aux profils. Conserver uniquement les autres
    # collecteurs dont le processus est encore effectivement signe et vivant,
    # puis ajouter ceux de ce demarrage. Un profil manuel ne fait ainsi jamais
    # oublier les PID CORE et aucun PID ancien/recycle n'est conserve aveuglement.
    pids_registre: dict[str, int] = {}
    for c in REGISTRE:
        pid_vivant = _pid_collecteur_existant(c, processus)
        if pid_vivant is not None:
            pids_registre[c["nom"]] = pid_vivant
    pids_registre.update(pids)
    if not _ecrire_pids_atomique(racine, {"run_id": rid, "ts_ms": int(time.time() * 1000),
                                          "profil": profil_normalise, "pids": pids_registre}):
        _compter_panne_interne("pids_inecrivable")
    return {
        "run_id": rid,
        "profil": profil_normalise,
        "selectionnes": len(collecteurs),
        "pids": pids,
        "reutilises": reutilises,
        "manquants": manquants,
    }


def demarrer_un(root: str | Path, nom: str, *, spawner=None) -> int | None:
    """Relance CIBLÉE d'UN collecteur (par nom) + met à jour le registre PID. Rend son PID (ou None)."""
    c = next((x for x in REGISTRE if x["nom"] == nom), None)
    if c is None:
        return None
    lance = spawner if spawner is not None else _spawn_pid
    pid = lance(c, Path(root))
    if pid:
        reg = _lire_pids(root)
        reg.setdefault("pids", {})[nom] = int(pid)
        if not _ecrire_pids_atomique(root, reg):
            _compter_panne_interne("pids_inecrivable")
    return pid


def enregistrer_pids(
    root: str | Path,
    *,
    run_id: str | None = None,
    procs: list[dict] | None = None,
    profil: str = "all",
) -> dict[str, Any]:
    """Après le démarrage (le lanceur spawn en `start /b`, éprouvé), TROUVE les PID des collecteurs qui
    tournent (par signature du REGISTRE) et les enregistre → base de l'arrêt CIBLÉ (Fix 5) SANS changer le
    spawn. Ne lève jamais. Rend {run_id, pids}."""
    racine = Path(root)
    procs = procs if procs is not None else _processus_projet(root)
    rid = run_id or ("run-" + os.urandom(6).hex())
    profil_normalise = normaliser_profil(profil, defaut="all")
    pids: dict[str, int] = {}
    for c in collecteurs_pour_profil(profil_normalise):
        nom, script = c["nom"], str(c["script"]).split("/")[-1]
        for p in procs:
            cl = p.get("cmd") or ""
            if ((" %s " % nom) in (" " + cl + " ")) or (script in cl):
                if isinstance(p.get("pid"), int):
                    pids[nom] = p["pid"]
                    break
    pids_registre: dict[str, int] = {}
    for c in REGISTRE:
        pid_vivant = _pid_collecteur_existant(c, procs)
        if pid_vivant is not None:
            pids_registre[c["nom"]] = pid_vivant
    pids_registre.update(pids)
    if not _ecrire_pids_atomique(racine, {"run_id": rid, "ts_ms": int(time.time() * 1000),
                                          "profil": profil_normalise, "pids": pids_registre}):
        _compter_panne_interne("pids_inecrivable")
    return {"run_id": rid, "profil": profil_normalise, "pids": pids}


def _ps(commande: str) -> str:
    """One-liner PowerShell (Windows) → stdout ; '' si non-Windows ou échec. Aucun motif large."""
    if os.name != "nt":
        return ""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", commande],  # noqa: S603,S607
                           capture_output=True, text=True, timeout=15)
        return r.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _parse_ps_process(out: str) -> list[dict[str, Any]]:
    try:
        d = json.loads(out) if out.strip() else []
    except ValueError:
        return []
    if isinstance(d, dict):
        d = [d]
    res = []
    for x in d:
        if isinstance(x, dict):
            res.append({"pid": x.get("ProcessId"), "ppid": x.get("ParentProcessId"),
                        "name": x.get("Name"), "cmd": x.get("CommandLine") or ""})
    return res


def _processus_projet(root: str | Path) -> list[dict[str, Any]]:
    """Process cmd/python signés NOS collecteurs (signature boucle_collecteur.cmd / script du registre).
    Registry-driven, JAMAIS un motif large type *hl_observer*. [] hors Windows."""
    # Ne filtre pas avec les signatures dans PowerShell : la commande d'inventaire contient alors
    # elle-meme ``collecter_userfills_vaults.py`` et se detecte comme un faux collecteur. On ne demande
    # que cmd/python, puis on applique ici la liste blanche issue du REGISTRE.
    out = _ps("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and "
              "($_.Name -eq 'cmd.exe' -or $_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') } "
              "| Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress")
    tous = [
        p for p in _parse_ps_process(out)
        if str(p.get("name") or "").lower() in {"cmd.exe", "python.exe", "pythonw.exe"}
    ]
    # Les wrappers de campagne sont eux aussi des processus HyperSmart signes.
    # Sans cette union, ``inspect_bounded_collectors`` perdait le compagnon
    # Copy-Vault pourtant vivant et marquait la collecte DEGRADED.
    inventaire = REGISTRE + COLLECTEURS_CAMPAGNE
    scripts = {
        str(c["script"]).replace("/", "\\").split("\\")[-1].lower()
        for c in inventaire
    }
    noms = {str(c["nom"]).lower() for c in inventaire}

    def signe(proc: dict[str, Any]) -> bool:
        ligne = str(proc.get("cmd") or "").lower()
        return (
            "boucle_collecteur.cmd" in ligne
            or any(script in ligne for script in scripts)
            or any((" %s " % nom) in (" " + ligne + " ") for nom in noms)
        )

    retenus = [p for p in tous if signe(p)]
    pids = {p.get("pid") for p in retenus if isinstance(p.get("pid"), int)}
    # Inclure recursivement les enfants des wrappers signes. Le Python BBO n'a pas toujours le chemin
    # du projet dans sa ligne de commande, mais son parent est exactement notre boucle_collecteur.cmd.
    while True:
        enfants = [p for p in tous if isinstance(p.get("pid"), int) and p.get("ppid") in pids]
        nouveaux = [p for p in enfants if p.get("pid") not in pids]
        if not nouveaux:
            break
        retenus.extend(nouveaux)
        pids.update(p["pid"] for p in nouveaux)
    return retenus


def pid_du_port(port: int = PORT_UI) -> int | None:
    out = _ps("(Get-NetTCPConnection -LocalPort %d -State Listen -ErrorAction SilentlyContinue "
              "| Select-Object -First 1 -ExpandProperty OwningProcess)" % port).strip()
    try:
        return int(out) if out else None
    except ValueError:
        return None


def _heartbeat_userfills(root: str | Path) -> int | None:
    try:
        d = json.loads((Path(root) / LOCK_USERFILLS).read_text(encoding="utf-8"))
        return int(d["heartbeat_ms"]) if d.get("heartbeat_ms") is not None else None
    except (OSError, ValueError, TypeError, KeyError):
        return None


def status_detaille(
    root: str | Path,
    *,
    maintenant: float | None = None,
    profil: str = "all",
) -> list[dict[str, Any]]:
    """Les 17 composants : pid enregistré, nb d'instances vivantes, heartbeat, âge du dernier log, état réel.
    Registry-driven. Sur Windows : instances/pid réels ; en sandbox : fraîcheur des logs seule."""
    profil_normalise = normaliser_profil(profil, defaut="all")
    collecteurs = collecteurs_pour_profil(profil_normalise)
    reg_pids = _lire_pids(root).get("pids", {})
    reg_pids = reg_pids if isinstance(reg_pids, dict) else {}
    procs = _processus_projet(root)
    hb_uf = _heartbeat_userfills(root)
    etats = etat_collecteurs(root, maintenant=maintenant, profil=profil_normalise)
    out = []
    for c, e in zip(collecteurs, etats):
        nom = c["nom"]
        instances, processus = _nombre_instances_logiques(c, procs)
        vivant = (instances > 0) if procs else (not e["mort"])
        out.append({"nom": nom, "profil": profil_collecteur(nom),
                    "pid_enregistre": reg_pids.get(nom), "instances": instances,
                    "processus": processus,
                    "heartbeat_ms": hb_uf if nom == "userfills-live" else None,
                    "age_log_min": e["age_minutes"], "limite_min": e["limite_minutes"],
                    "log_mort": e["mort"], "etat": "VIVANT" if vivant else "MORT"})
    return out


def arreter_cible(root: str | Path, *, procs: list[dict] | None = None,
                  killer: Callable[[int], bool] | None = None, owner: int | None = -1) -> dict[str, Any]:
    """Arrêt CIBLÉ (Fix 5) : SEULEMENT les PID enregistrés du run + enfants VÉRIFIÉS + process signés
    registre (boucle_collecteur.cmd / <script>) + détenteur validé du port 8794 + PID du verrou userfills.
    JAMAIS de motif large (*hl_observer*/*projet*). Rend {cibles, arretes, port_owner}.
    `procs`/`killer`/`owner` injectables pour test (défaut = réel Windows)."""
    racine = Path(root)
    cibles: set[int] = set()
    for pid in (_lire_pids(root).get("pids", {}) or {}).values():        # 1) PID enregistrés du run
        try:
            cibles.add(int(pid))
        except (TypeError, ValueError):
            continue
    liste = procs if procs is not None else _processus_projet(root)
    scripts = {str(c["script"]).split("/")[-1] for c in REGISTRE}
    noms = {c["nom"] for c in REGISTRE}
    for p in liste:                                                     # 2) process SIGNÉS registre
        cl = p.get("cmd") or ""
        if any((" %s " % n) in (" " + cl + " ") for n in noms) or any(s in cl for s in scripts):
            if isinstance(p.get("pid"), int):
                cibles.add(p["pid"])
    par_parent: dict[Any, list] = {}
    for p in liste:
        par_parent.setdefault(p.get("ppid"), []).append(p.get("pid"))
    for pid in list(cibles):                                            # enfants VÉRIFIÉS (parent ∈ cibles)
        for enf in par_parent.get(pid, []):
            if isinstance(enf, int):
                cibles.add(enf)
    owner_pid = pid_du_port(PORT_UI) if owner == -1 else owner          # 3) détenteur validé du port 8794
    if owner_pid:
        cibles.add(owner_pid)
    try:                                                                # 4) PID du verrou userfills
        d = json.loads((racine / LOCK_USERFILLS).read_text(encoding="utf-8"))
        if d.get("pid"):
            cibles.add(int(d["pid"]))
    except (OSError, ValueError, TypeError):
        import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
        _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
    tuer = killer if killer is not None else (
        lambda pid: _ps("try { Stop-Process -Id %d -Force -ErrorAction Stop; 'ok' } catch { '' }" % pid).strip() == "ok")
    arretes = [pid for pid in sorted(cibles) if tuer(pid)]
    try:
        (racine / LOCK_USERFILLS).unlink()
    except OSError:
        import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
        _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
    return {"cibles": sorted(cibles), "arretes": arretes, "port_owner": owner_pid}


def _cli(argv: list[str]) -> int:
    root = Path.cwd()
    cmd = argv[0] if argv else "status"
    if cmd == "demarrer-tous":
        profil = argv[1] if len(argv) > 1 else "core"
        try:
            r = demarrer_tous(root, profil=profil)
        except ValueError as exc:
            print("[collecteurs] REFUS: %s (attendus: %s)" % (
                exc, ", ".join(PROFILS_VALIDES)), flush=True)
            return 2
        print("[collecteurs] run_id=%s demarres=%d/%d manquants=%s" % (
            r["run_id"], len(r["pids"]), r["selectionnes"], r["manquants"] or "aucun"), flush=True)
        print("[collecteurs] profil=%s reutilises=%s" % (
            r["profil"], r["reutilises"] or "aucun"), flush=True)
        # Une source OBLIGATOIRE qui n'a pas démarré doit bloquer le lanceur (sortie non-zero),
        # pas seulement s'afficher : le moteur ne doit pas tourner au-dessus de collecteurs morts.
        requis_du_run = collecteurs_requis_pour_run(profil)
        requis_manquants = [n for n in r["manquants"] if n in requis_du_run]
        if requis_manquants:
            print("[collecteurs] ECHEC: sources obligatoires non demarrees: %s" % ", ".join(
                requis_manquants), flush=True)
            return 3
        return 0
    if cmd == "enregistrer-pids":
        profil = argv[1] if len(argv) > 1 and argv[1] in PROFILS_VALIDES else "all"
        rid_index = 2 if profil != "all" or (len(argv) > 1 and argv[1] == "all") else 1
        rid = argv[rid_index] if len(argv) > rid_index else None
        r = enregistrer_pids(root, run_id=rid, profil=profil)
        print("[collecteurs] PID enregistres : %d/%d (profil=%s run_id=%s)" % (
            len(r["pids"]), len(collecteurs_pour_profil(profil)), profil, r["run_id"]), flush=True)
        return 0
    if cmd == "demarrer" and len(argv) > 1:
        print("[collecteurs] %s -> pid=%s" % (argv[1], demarrer_un(root, argv[1])), flush=True)
        return 0
    if cmd == "arreter":
        r = arreter_cible(root)
        print("[collecteurs] arret CIBLE : %d process arretes (port8794=%s ; jamais de kill global)"
              % (len(r["arretes"]), r["port_owner"]), flush=True)
        return 0
    profil = argv[1] if len(argv) > 1 else "all"
    try:
        collecteurs = collecteurs_pour_profil(profil)
    except ValueError as exc:
        print("[collecteurs] REFUS: %s" % exc, flush=True)
        return 2
    print("===  STATUT DES %d COLLECTEURS  (profil=%s)  ===" % (
        len(collecteurs), normaliser_profil(profil, defaut="all")), flush=True)
    vivants = 0
    for s in status_detaille(root, profil=profil):
        vivants += 1 if s["etat"] == "VIVANT" else 0
        hb = "" if s["heartbeat_ms"] is None else (" hb=%s" % s["heartbeat_ms"])
        age = "?" if s["age_log_min"] is None else ("%.1fmin" % s["age_log_min"])
        print("  %-24s %-6s inst=%d pid=%s log=%s%s" % (
            s["nom"], s["etat"], s["instances"], s["pid_enregistre"], age, hb), flush=True)
    print("  -> %d/%d VIVANTS" % (vivants, len(collecteurs)), flush=True)
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
