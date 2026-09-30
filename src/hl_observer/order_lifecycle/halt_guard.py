"""[ARB lot2 #17] HALT GUARD : aucun arbitrage ne peut naître entre un marché ACTIF et une venue temporairement
HALTÉE. Un prix affiché sur une venue haltée est figé/périmé — l'« écart » qu'on croit voir est un artefact, pas
une opportunité. Les DEUX venues doivent être TRADING. Statut inconnu → bloqué (fail-closed). Pur, 0 réseau, 0 ordre.
"""
from __future__ import annotations

from typing import Any

TRADING = "TRADING"


def _actif(statut: Any) -> bool:
    return str(statut).upper() == TRADING


def peut_arbitrer(statut_venue_a: Any, statut_venue_b: Any) -> dict[str, Any]:
    """Arbitrage autorisé seulement si les deux venues sont TRADING. Une haltée/inconnue → refus."""
    a, b = _actif(statut_venue_a), _actif(statut_venue_b)
    haltees = [n for n, ok in (("A", a), ("B", b)) if not ok]
    ok = a and b
    return {"peut_arbitrer": bool(ok), "venues_non_trading": haltees,
            "raison": ("OK" if ok else "VENUE_HALTEE_OU_INCONNUE")}


__all__ = ["peut_arbitrer", "TRADING"]
