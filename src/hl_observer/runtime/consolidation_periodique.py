"""CONSOLIDATION PÉRIODIQUE DU REPLAY — la session doit se suffire (21/07).

LE DÉFAUT MESURÉ
----------------
La consolidation du replay n'est lancée qu'à **deux** endroits :

    LANCER_HYPERSMART.cmd:287   une fois, AU DÉMARRAGE (`--archive-run`)
    TOUT-TESTER.cmd             étape 2, quand on lance l'audit

Entre les deux, rien. Constat de ce soir, session en cours depuis ~11 h :

    runtime/replay/_merged/marks.jsonl        20,7 Mo   **figé depuis 11,5 h**
    runtime/replay/_merged/candidates.jsonl  215,1 Mo   **figé depuis 11,5 h**
    runtime/replay/marks.<pid>.jsonl                    écrits en continu

Les collecteurs vont très bien : 276 coins marqués, un mark toutes les **61 s**, 88,7 % des
candidats couverts. Ce n'est pas la collecte qui manque — c'est le **rangement**.

CE QUE ÇA CASSE
---------------
Tout ce qui lit le consolidé travaille sur des données vieilles de 11 heures :

    backtesting/recherche_scenario   la recherche de pépites
    tools/pnl_des_refus              le PnL des refus
    tools/qualite_donnees_replay     l'audit de qualité
    copy_wallet/marks_source         (immunisé depuis ce soir : lit AUSSI les shards)

C'est exactement ce qui a réduit le markout copy à 2,4 % de couverture : le pipeline joignait
7 184 fills récents à des marks qui s'arrêtaient 11 h plus tôt.

CE MODULE
---------
Il consolide **si et seulement si** le consolidé a pris du retard, à chaque passe du feeder
(ré-exécuté toutes les ~10 min). La session devient autonome : plus besoin d'un audit ou d'un
redémarrage pour que le consolidé suive.

Règles :
  * **ne lève JAMAIS** — un rangement qui tue le feeder serait pire que le désordre ;
  * **verrou** : deux passes ne consolident pas en même temps (verrou périmé = ignoré, sinon
    un crash bloquerait la consolidation pour toujours) ;
  * **non destructif** : `replay_recorder` fusionne, il n'efface pas les shards ;
  * **dit ce qu'il fait**, pour qu'un retard reste visible au lieu d'être silencieux.

PAPER only : ranger des fichiers n'est pas passer un ordre.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

#: au-delà de ce retard, le consolidé est trop vieux pour ce qui le lit. 20 min = deux passes
#: de feeder : on tolère qu'une passe saute sans déclencher une consolidation à chaque fois.
RETARD_MAX_S = 20 * 60.0
#: au-delà, un verrou est considéré comme abandonné (processus mort en cours de route).
VERROU_PERIME_S = 15 * 60.0
#: budget : la consolidation ne doit jamais retarder une passe de feeder indéfiniment.
BUDGET_S = 240.0

VERROU = Path("runtime") / "replay" / ".consolidation.lock"


def retard_s(root: str | Path = ".") -> float | None:
    """Depuis combien de temps le consolidé n'a-t-il pas bougé ? `None` s'il n'existe pas."""
    p = Path(root) / "runtime" / "replay" / "_merged" / "marks.jsonl"
    try:
        return max(0.0, time.time() - p.stat().st_mtime)
    except OSError:
        return None


def _verrou_pris(chemin: Path) -> bool:
    """True si un autre processus consolide en ce moment. Un verrou périmé est ignoré ET
    supprimé : sinon un crash bloquerait la consolidation pour toujours."""
    try:
        age = time.time() - chemin.stat().st_mtime
    except OSError:
        return False
    if age > VERROU_PERIME_S:
        try:
            chemin.unlink()
        except OSError:
            pass
        return False
    return True


def consolider_si_en_retard(root: str | Path = ".", *, retard_max_s: float = RETARD_MAX_S,
                            budget_s: float = BUDGET_S,
                            forcer: bool = False) -> dict[str, Any]:
    """Consolide le replay si le consolidé a pris du retard. **Ne lève jamais.**

    Retourne `{fait, retard_avant_s, motif, duree_s}` — un dictionnaire qu'on peut imprimer,
    parce qu'un retard silencieux est exactement ce qui a coûté 11 heures de mesure.
    """
    racine = Path(root)
    out: dict[str, Any] = {"fait": False, "motif": "", "duree_s": 0.0,
                           "real_execution": False}
    try:
        r = retard_s(racine)
        out["retard_avant_s"] = None if r is None else round(r, 1)
        out["retard_avant_h"] = None if r is None else round(r / 3600.0, 2)
        if not forcer and r is not None and r < float(retard_max_s):
            out["motif"] = "consolide a jour (%.0f min)" % (r / 60.0)
            return out
        verrou = racine / VERROU
        if _verrou_pris(verrou):
            out["motif"] = "une autre passe consolide deja"
            return out
        verrou.parent.mkdir(parents=True, exist_ok=True)
        try:
            verrou.write_text(str(os.getpid()), encoding="utf-8")
        except OSError:
            pass
        t0 = time.time()
        try:
            p = subprocess.run(
                [sys.executable, "-m", "hl_observer.runtime.replay_recorder",
                 "--base", str(racine / "runtime" / "replay")],
                capture_output=True, text=True, timeout=float(budget_s),
                encoding="utf-8", errors="replace")
            out["fait"] = p.returncode == 0
            out["motif"] = ("consolide" if p.returncode == 0
                            else "echec (code %s)" % p.returncode)
        except subprocess.TimeoutExpired:
            out["motif"] = "budget depasse (%.0f s) : consolidation reportee" % budget_s
        except Exception as exc:  # noqa: BLE001
            out["motif"] = "erreur : %s" % str(exc)[:120]
        finally:
            out["duree_s"] = round(time.time() - t0, 1)
            try:
                verrou.unlink()
            except OSError:
                pass
        out["retard_apres_s"] = retard_s(racine)
        return out
    except Exception as exc:  # noqa: BLE001
        # un rangement ne doit JAMAIS tuer l'appelant.
        out["motif"] = "erreur inattendue : %s" % str(exc)[:120]
        return out


def ligne_de_rapport(res: dict[str, Any]) -> str:
    """Une ligne lisible pour la sortie du feeder. Un retard doit se VOIR."""
    r = res.get("retard_avant_h")
    if res.get("fait"):
        return ("  CONSOLIDATION : replay consolide (retard de %.1f h rattrape, %.0f s)"
                % (r or 0.0, res.get("duree_s") or 0.0))
    if r is not None and r * 3600.0 >= RETARD_MAX_S:
        return ("  !! CONSOLIDATION EN RETARD de %.1f h — %s. Ce qui lit le consolide "
                "(recherche, PnL des refus, audit qualite) travaille sur du vieux."
                % (r, res.get("motif") or "?"))
    return "  consolidation : %s" % (res.get("motif") or "rien a faire")


__all__ = ["RETARD_MAX_S", "VERROU_PERIME_S", "BUDGET_S", "VERROU", "retard_s",
           "consolider_si_en_retard", "ligne_de_rapport"]
