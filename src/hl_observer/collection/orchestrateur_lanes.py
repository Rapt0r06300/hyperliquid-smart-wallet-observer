"""Orchestration d'allocation multi-sources — idées #44-50.

Fonction PURE qui répartit les leaders entre les sources de collecte selon leur activité
prédite et les capacités réelles :
- **WS** (slots rares, cap ~10 users/IP → `lanes_ws × slots_par_lane`) : aux plus actifs ;
- **poll REST** (contourne le cap, débit borné) : la couche intermédiaire ;
- **nœud local** (tous les users, si actif) : filet pour le reste ;
- sinon : non couverts (signalés pour re-prioriser).

Les leaders WS sont répartis en **shards disjoints** (round-robin) → 0 doublon entre lanes.
PAPER / lecture seule. Aucune décision d'ordre.
"""
from __future__ import annotations

import math
from collections.abc import Sequence


def recommander_nb_lanes(n_leaders_actifs: int, *, slots_par_lane: int = 10, max_lanes: int = 8) -> int:
    """Nombre de lanes WS pour couvrir les leaders actifs (borné)."""
    if n_leaders_actifs <= 0 or slots_par_lane <= 0:
        return 1
    return max(1, min(max_lanes, math.ceil(n_leaders_actifs / slots_par_lane)))


def orchestrer(classement: Sequence[tuple[str, float]], *, lanes_ws: int = 4,
               slots_par_lane: int = 10, poll_capacite: int = 200, node_actif: bool = False,
               seuil_actif: float = 0.0) -> dict:
    """Répartit `classement` (leader, score décroissant) entre WS / poll / nœud.

    `seuil_actif` : un leader sous ce score prédit n'occupe pas de slot WS (repli poll/nœud).
    """
    cap_ws = max(0, lanes_ws) * max(0, slots_par_lane)
    assignations: dict[str, dict] = {}
    ws_pris = 0
    poll_pris = 0
    non_couverts: list[str] = []
    for leader, score in classement:
        if ws_pris < cap_ws and score > seuil_actif:
            lane = ws_pris % max(1, lanes_ws)
            assignations[leader] = {"source": "ws", "lane": lane, "score": score}
            ws_pris += 1
        elif poll_pris < poll_capacite:
            assignations[leader] = {"source": "poll", "lane": None, "score": score}
            poll_pris += 1
        elif node_actif:
            assignations[leader] = {"source": "node", "lane": None, "score": score}
        else:
            non_couverts.append(leader)
    # #45 : recommander un nombre de lanes adapté au nombre de leaders « actifs »
    n_actifs = sum(1 for _, s in classement if s > seuil_actif)
    return {
        "assignations": assignations,
        "resume": {"ws": ws_pris, "poll": poll_pris,
                   "node": sum(1 for a in assignations.values() if a["source"] == "node"),
                   "non_couverts": len(non_couverts)},
        "non_couverts": non_couverts,
        "lanes_ws_recommandees": recommander_nb_lanes(n_actifs, slots_par_lane=slots_par_lane),
        "capacite_ws": cap_ws,
    }


def leaders_par_lane(resultat: dict, lane: int) -> list[str]:
    """Liste des leaders assignés à une lane WS donnée (pour --shard d'une lane)."""
    return sorted(l for l, a in resultat.get("assignations", {}).items()
                  if a.get("source") == "ws" and a.get("lane") == lane)
