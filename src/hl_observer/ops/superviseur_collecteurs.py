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
REGISTRE: tuple[dict[str, Any], ...] = (
    {"nom": "carry-feeder", "script": "tools/ecrire_carry_spot_inputs.py",
     "intervalle_s": 240, "args": (), "limite_minutes": 15.0},
    {"nom": "marks-collector", "script": "tools/ecrire_marks_tous_coins.py",
     "intervalle_s": 60, "args": ("--une-fois",), "limite_minutes": 5.0},
    {"nom": "liq-collector", "script": "tools/collecter_liquidations.py",
     "intervalle_s": 300, "args": ("--une-fois",), "limite_minutes": 20.0},
    {"nom": "venues-collector", "script": "tools/collecter_dispersion_venues.py",
     "intervalle_s": 300, "args": ("--une-fois",), "limite_minutes": 20.0},
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


def etat_collecteurs(root: Path, *, maintenant: float | None = None) -> list[dict[str, Any]]:
    """Un dict par collecteur du REGISTRE : {nom, age_minutes, limite_minutes, mort}."""
    out: list[dict[str, Any]] = []
    for c in REGISTRE:
        age = age_log_minutes(root, c["nom"], maintenant=maintenant)
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
