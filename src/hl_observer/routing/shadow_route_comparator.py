"""[CROSS-VENUE pépite 243] SHADOW-ROUTE COMPARATOR : pour une VRAIE opportunité paper, simuler EN PARALLÈLE les
routes NON CHOISIES (en shadow, sans changer le trade réel) afin d'améliorer le moteur d'exécution. On compare le
résultat de la route retenue à ce qu'auraient donné les autres, sans jamais toucher à la décision réelle — c'est de
la mesure, pas de l'exécution. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def comparer(*, route_choisie: str, resultats_bps: Mapping[str, Any]) -> dict[str, Any]:
    """Compare le résultat (bps) de la route choisie aux routes shadow. `resultats_bps` = {route: edge_net_bps}.
    Renvoie le classement et si une route shadow aurait fait mieux (delta), sans rien exécuter. Route choisie
    absente des résultats → non comparable."""
    valides = {str(k): float(v) for k, v in resultats_bps.items() if isinstance(v, (int, float))}
    if str(route_choisie) not in valides:
        return {"comparable": False, "raison": "ROUTE_CHOISIE_SANS_RESULTAT"}
    choisi = valides[str(route_choisie)]
    meilleure = max(valides, key=lambda k: valides[k])
    delta = round(valides[meilleure] - choisi, 4)
    return {"comparable": True, "route_choisie": str(route_choisie), "edge_choisi_bps": round(choisi, 4),
            "meilleure_route": meilleure, "gain_manque_bps": delta,
            "choix_optimal": bool(meilleure == str(route_choisie)), "shadow_only": True}


__all__ = ["comparer"]
