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

#: 🔴 SOURCE UNIQUE — doit refléter les lignes `start ... boucle_collecteur.cmd` de
#: LANCER_HYPERSMART.cmd. Le test `test_le_REGISTRE_correspond_au_LANCEUR` compare les deux :
#: si quelqu'un ajoute un collecteur au lanceur sans l'ajouter ici, le test rougit — sinon le
#: nouveau collecteur mourrait SANS supervision, exactement la panne qu'on vient de payer.
#: limite_minutes : au-delà de ce silence du log, le collecteur est déclaré MORT.
#: (le log est écrit à CHAQUE passe ; silence sain max ≈ cadence + durée d'une passe)
#: 25/07 — REGISTRE ÉTENDU aux 17 collecteurs RÉELLEMENT démarrés par l'AUTOPILOT (avant : 7, dont
#: carry-feeder qui était COUPÉ dans le lanceur -> canari 17 vs 7 rouge). Désormais SOURCE UNIQUE
#: utilisée par : AUTOPILOT (`demarrer_tous`), `status` (status_detaille), watchdog (verifier_et_relancer),
#: arrêt ciblé (arreter_cible) et les tests. Une seule liste, plus de dérive possible.
#: `une_fois` = True si le script fait UNE passe puis rend la main (boucle_collecteur relance à l'intervalle).
REGISTRE: tuple[dict[str, Any], ...] = (
    {"nom": "marks-collector", "script": "tools/ecrire_marks_tous_coins.py",
     "intervalle_s": 60, "args": ("--une-fois",), "limite_minutes": 5.0},
    {"nom": "allmids-collector", "script": "tools/collecter_allmids.py",
     "intervalle_s": 15, "args": ("--une-fois",), "limite_minutes": 5.0},
    {"nom": "liq-collector", "script": "tools/collecter_liquidations.py",
     "intervalle_s": 300, "args": ("--une-fois",), "limite_minutes": 20.0},
    {"nom": "venues-collector", "script": "tools/collecter_dispersion_venues.py",
     "intervalle_s": 60, "args": ("--une-fois",), "limite_minutes": 20.0},
    {"nom": "carnet-collector", "script": "tools/collecter_carnet.py",
     "intervalle_s": 60, "args": ("--une-fois",), "limite_minutes": 20.0},
    {"nom": "overshoot-collector", "script": "tools/collecter_overshoots.py",
     "intervalle_s": 10, "args": ("--une-fois",), "limite_minutes": 5.0},
    {"nom": "vault-collector", "script": "tools/collecter_vaults.py",
     "intervalle_s": 300, "args": ("--une-fois",), "limite_minutes": 20.0},
    {"nom": "scorer-vaults", "script": "tools/scorer_vaults.py",
     "intervalle_s": 600, "args": ("--une-fois",), "limite_minutes": 25.0},
    {"nom": "backfill-fills", "script": "tools/backfill_vault_fills.py",
     "intervalle_s": 14400, "args": ("--une-fois",), "limite_minutes": 480.0},
    {"nom": "backfill-candles-vaults", "script": "tools/backfill_candles_vaults.py",
     "intervalle_s": 14400, "args": ("--une-fois",), "limite_minutes": 480.0},
    {"nom": "pipeline-reel", "script": "tools/pipeline_copie_reel.py",
     "intervalle_s": 1800, "args": ("--une-fois",), "limite_minutes": 60.0},
    {"nom": "geler-prelim", "script": "tools/geler_prelim_copie.py",
     "intervalle_s": 3600, "args": ("--une-fois",), "limite_minutes": 120.0},
    # PERSISTANTS : écrivent la DATA en continu, pas un log par seconde -> la vie se mesure au HEARTBEAT
    # (fraîcheur du fichier), JAMAIS au log (sinon faux STALL + le watchdog dupliquerait un collecteur vivant).
    {"nom": "userfills-live", "script": "tools/collecter_userfills_vaults.py",
     "intervalle_s": 5, "args": (), "limite_minutes": 5.0,
     "heartbeat": "runtime/data/userfills_live.lock"},
    {"nom": "bbo-collector", "script": "tools/collecter_bbo.py",
     "intervalle_s": 5, "args": (), "limite_minutes": 5.0,
     "heartbeat": "runtime/data/bbo_heartbeat.json"},
    {"nom": "experimental-paper", "script": "tools/experimental_paper_tick.py",
     "intervalle_s": 60, "args": ("--une-fois",), "limite_minutes": 20.0},
    {"nom": "copy-whitelist", "script": "tools/ecrire_copy_whitelist.py",
     "intervalle_s": 21600, "args": (), "limite_minutes": 570.0},
    {"nom": "rapport-quotidien", "script": "tools/rapport_quotidien.py",
     "intervalle_s": 21600, "args": (), "limite_minutes": 570.0},
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
            pass                                   # heartbeat absent -> repli honnête sur le log
    return age_log_minutes(root, c["nom"], maintenant=maintenant)


def etat_collecteurs(root: Path, *, maintenant: float | None = None) -> list[dict[str, Any]]:
    """Un dict par collecteur du REGISTRE : {nom, age_minutes, limite_minutes, mort}."""
    out: list[dict[str, Any]] = []
    for c in REGISTRE:
        age = age_vie_minutes(root, c, maintenant=maintenant)
        out.append({
            "nom": c["nom"],
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


def verifier_et_relancer(
    root: str | Path,
    *,
    maintenant: float | None = None,
    lanceur: Callable[[list[str], Path], bool] | None = None,
    cooldown_s: float = COOLDOWN_S,
) -> dict[str, Any]:
    """Une passe de supervision. Retourne un rapport, ne lève JAMAIS.

    rapport = {actif, morts: [noms], relances: [noms], en_cooldown: [noms]}
    """
    try:
        racine = Path(root)
        if not actif():
            return {"actif": False, "morts": [], "relances": [], "en_cooldown": []}
        now = maintenant if maintenant is not None else time.time()
        lancer = lanceur if lanceur is not None else _lanceur_windows
        journal = _lire_journal(racine)
        morts: list[str] = []
        relances: list[str] = []
        en_cooldown: list[str] = []

        for c, etat in zip(REGISTRE, etat_collecteurs(racine, maintenant=now)):
            if not etat["mort"]:
                continue
            morts.append(c["nom"])
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
            if ok:
                relances.append(c["nom"])

        if morts:
            journal["derniere_passe_ts"] = now
            _ecrire_journal(racine, journal)
        return {"actif": True, "morts": morts, "relances": relances,
                "en_cooldown": en_cooldown}
    except Exception as exc:  # noqa: BLE001 — jamais d'exception vers le moteur
        try:
            from hl_observer.ops.echec_silencieux import noter
            noter("superviseur_collecteurs", exc)
        except Exception:  # noqa: BLE001
            # meme le compteur officiel est en panne : on compte LOCALEMENT (jamais muet)
            _compter_panne_interne("noter_indisponible")
        return {"actif": True, "morts": [], "relances": [], "en_cooldown": [],
                "erreur": str(exc)[:200]}


# ─────────────────────────────────────────────────────────────────────────────────────────────
#  DÉMARRAGE / STATUS / ARRÊT CIBLÉ — pilotés par le MÊME REGISTRE (source unique, 25/07).
#  Le lanceur (cmd) appelle ces fonctions : plus aucune liste de collecteurs dupliquée en .cmd.
# ─────────────────────────────────────────────────────────────────────────────────────────────
PIDS_RELPATH = Path("runtime") / "data" / "collecteurs_pids.json"
PORT_UI = 8794
LOCK_USERFILLS = Path("runtime") / "data" / "userfills_live.lock"


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


def demarrer_tous(root: str | Path, *, run_id: str | None = None,
                  spawner: Callable[[dict, Path], int | None] | None = None) -> dict[str, Any]:
    """Démarre les 17 collecteurs du REGISTRE et ENREGISTRE leur PID (base de l'arrêt CIBLÉ).
    Ne lève jamais. Rend {run_id, pids, manquants}."""
    racine = Path(root)
    rid = run_id or ("run-" + os.urandom(6).hex())
    lance = spawner if spawner is not None else _spawn_pid
    pids: dict[str, int] = {}
    manquants: list[str] = []
    for c in REGISTRE:
        try:
            pid = lance(c, racine)
        except Exception:  # noqa: BLE001 — un spawner injecté ne doit pas nous tuer
            pid = None
        if pid:
            pids[c["nom"]] = int(pid)
        else:
            manquants.append(c["nom"])
    try:
        p = racine / PIDS_RELPATH
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"run_id": rid, "ts_ms": int(time.time() * 1000), "pids": pids},
                                ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        _compter_panne_interne("pids_inecrivable")
    return {"run_id": rid, "pids": pids, "manquants": manquants}


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
        try:
            (Path(root) / PIDS_RELPATH).write_text(json.dumps(reg, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            _compter_panne_interne("pids_inecrivable")
    return pid


def enregistrer_pids(root: str | Path, *, run_id: str | None = None,
                     procs: list[dict] | None = None) -> dict[str, Any]:
    """Après le démarrage (le lanceur spawn en `start /b`, éprouvé), TROUVE les PID des collecteurs qui
    tournent (par signature du REGISTRE) et les enregistre → base de l'arrêt CIBLÉ (Fix 5) SANS changer le
    spawn. Ne lève jamais. Rend {run_id, pids}."""
    racine = Path(root)
    procs = procs if procs is not None else _processus_projet(root)
    rid = run_id or ("run-" + os.urandom(6).hex())
    pids: dict[str, int] = {}
    for c in REGISTRE:
        nom, script = c["nom"], str(c["script"]).split("/")[-1]
        for p in procs:
            cl = p.get("cmd") or ""
            if ((" %s " % nom) in (" " + cl + " ")) or (script in cl):
                if isinstance(p.get("pid"), int):
                    pids[nom] = p["pid"]
                    break
    try:
        pf = racine / PIDS_RELPATH
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(json.dumps({"run_id": rid, "ts_ms": int(time.time() * 1000), "pids": pids},
                                 ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        _compter_panne_interne("pids_inecrivable")
    return {"run_id": rid, "pids": pids}


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
    out = _ps("Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and "
              "($_.CommandLine -like '*boucle_collecteur.cmd*' -or $_.CommandLine -like '*collecter_userfills_vaults.py*') } "
              "| Select-Object ProcessId,ParentProcessId,Name,CommandLine | ConvertTo-Json -Compress")
    return _parse_ps_process(out)


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


def status_detaille(root: str | Path, *, maintenant: float | None = None) -> list[dict[str, Any]]:
    """Les 17 composants : pid enregistré, nb d'instances vivantes, heartbeat, âge du dernier log, état réel.
    Registry-driven. Sur Windows : instances/pid réels ; en sandbox : fraîcheur des logs seule."""
    reg_pids = _lire_pids(root).get("pids", {})
    reg_pids = reg_pids if isinstance(reg_pids, dict) else {}
    procs = _processus_projet(root)
    hb_uf = _heartbeat_userfills(root)
    etats = etat_collecteurs(root, maintenant=maintenant)
    out = []
    for c, e in zip(REGISTRE, etats):
        nom, script = c["nom"], str(c["script"]).split("/")[-1]
        insts = [p for p in procs if (" %s " % nom) in (" " + (p["cmd"] or "") + " ") or script in (p["cmd"] or "")]
        vivant = (len(insts) > 0) if procs else (not e["mort"])
        out.append({"nom": nom, "pid_enregistre": reg_pids.get(nom), "instances": len(insts),
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
        pass
    tuer = killer if killer is not None else (
        lambda pid: _ps("try { Stop-Process -Id %d -Force -ErrorAction Stop; 'ok' } catch { '' }" % pid).strip() == "ok")
    arretes = [pid for pid in sorted(cibles) if tuer(pid)]
    try:
        (racine / LOCK_USERFILLS).unlink()
    except OSError:
        pass
    return {"cibles": sorted(cibles), "arretes": arretes, "port_owner": owner_pid}


def _cli(argv: list[str]) -> int:
    root = Path.cwd()
    cmd = argv[0] if argv else "status"
    if cmd == "demarrer-tous":
        r = demarrer_tous(root)
        print("[collecteurs] run_id=%s demarres=%d/%d manquants=%s" % (
            r["run_id"], len(r["pids"]), len(REGISTRE), r["manquants"] or "aucun"), flush=True)
        return 0
    if cmd == "enregistrer-pids":
        rid = argv[1] if len(argv) > 1 else None
        r = enregistrer_pids(root, run_id=rid)
        print("[collecteurs] PID enregistres : %d/%d (run_id=%s)" % (len(r["pids"]), len(REGISTRE), r["run_id"]), flush=True)
        return 0
    if cmd == "demarrer" and len(argv) > 1:
        print("[collecteurs] %s -> pid=%s" % (argv[1], demarrer_un(root, argv[1])), flush=True)
        return 0
    if cmd == "arreter":
        r = arreter_cible(root)
        print("[collecteurs] arret CIBLE : %d process arretes (port8794=%s ; jamais de kill global)"
              % (len(r["arretes"]), r["port_owner"]), flush=True)
        return 0
    print("===  STATUT DES 17 COLLECTEURS  (registre unique)  ===", flush=True)
    vivants = 0
    for s in status_detaille(root):
        vivants += 1 if s["etat"] == "VIVANT" else 0
        hb = "" if s["heartbeat_ms"] is None else (" hb=%s" % s["heartbeat_ms"])
        age = "?" if s["age_log_min"] is None else ("%.1fmin" % s["age_log_min"])
        print("  %-24s %-6s inst=%d pid=%s log=%s%s" % (
            s["nom"], s["etat"], s["instances"], s["pid_enregistre"], age, hb), flush=True)
    print("  -> %d/%d VIVANTS" % (vivants, len(REGISTRE)), flush=True)
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
