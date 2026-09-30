"""[CROSS-VENUE pépite 231] ROUTE GRAPH : représenter chaque couple {venue, instrument, side, execution type} comme
une ROUTE, et comparer leur COÛT EXÉCUTABLE COMPLET (frais + spread + slippage attendu + premium de fiabilité), pas
seulement les frais affichés. Deux routes « à mêmes frais » ne se valent pas si l'une dérape plus. On classe les
routes par coût total. Route au coût non mesurable → écartée (jamais supposée bon marché). Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def cle_route(*, venue: str, instrument: str, side: str, exec_type: str) -> str:
    return "|".join([str(venue).upper(), str(instrument).upper(), str(side).upper(), str(exec_type).upper()])


def cout_total_bps(route: dict[str, Any]) -> Any:
    """Coût exécutable complet = frais + spread + slippage + premium fiabilité (bps). Composant manquant →
    UNMEASURABLE (on ne sous-estime jamais le coût d'une route)."""
    postes = ("frais_bps", "spread_bps", "slippage_bps", "premium_fiabilite_bps")
    if not all(isinstance(route.get(p), (int, float)) for p in postes):
        return UNMEASURABLE
    return round(sum(float(route[p]) for p in postes), 4)


def classer(routes: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Classe les routes mesurables par coût total croissant ; écarte celles au coût non mesurable."""
    mesurables, ecartees = [], []
    for r in routes:
        c = cout_total_bps(r)
        if c == UNMEASURABLE:
            ecartees.append(cle_route(**{k: r.get(k, "") for k in ("venue", "instrument", "side", "exec_type")}))
        else:
            mesurables.append({"cle": cle_route(**{k: r.get(k, "") for k in ("venue", "instrument", "side", "exec_type")}),
                               "cout_total_bps": c})
    mesurables.sort(key=lambda x: x["cout_total_bps"])
    return {"classees": mesurables, "meilleure": (mesurables[0] if mesurables else None),
            "ecartees_non_mesurables": ecartees}


__all__ = ["cle_route", "cout_total_bps", "classer", "UNMEASURABLE"]
