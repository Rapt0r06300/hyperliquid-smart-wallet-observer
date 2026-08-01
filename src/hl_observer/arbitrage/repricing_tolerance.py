"""[CROSS-VENUE #24] TICK-BASED REPRICING TOLERANCE : ne recalculer/replacer un ordre QUE si le prix cible a
réellement bougé d'au moins X ticks économiquement significatifs. Replacer pour un mouvement d'un sous-tick
détruit du rendement en churn sans rien gagner. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def doit_repricer(prix_actuel: Any, prix_cible: Any, *, tick: float, min_ticks: float = 1.0) -> dict[str, Any]:
    """Repricing autorisé seulement si |cible − actuel| ≥ min_ticks × tick. Sinon on garde l'ordre en place."""
    if not all(isinstance(x, (int, float)) for x in (prix_actuel, prix_cible)) or not (isinstance(tick, (int, float)) and tick > 0):
        return {"repricer": False, "raison": "NON_MESURABLE"}
    delta = abs(float(prix_cible) - float(prix_actuel))
    ticks = delta / float(tick)
    ok = ticks >= float(min_ticks)
    return {"repricer": bool(ok), "delta_ticks": round(ticks, 4), "min_ticks": float(min_ticks),
            "raison": ("MOUVEMENT_SIGNIFICATIF" if ok else "SOUS_LA_TOLERANCE")}


__all__ = ["doit_repricer"]
