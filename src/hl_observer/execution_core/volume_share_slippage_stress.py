"""[ALL #97] VOLUME-SHARE SLIPPAGE STRESS : modèle CHALLENGER (en plus du book-walk) où l'impact croît avec le
CARRÉ de (order_size / market_volume) — le VolumeShareSlippageModel de LEAN. Il ne remplace pas le carnet causal :
il sert surtout à DÉTECTER des tailles absurdes (une taille qui représente une grosse fraction du volume implique un
impact explosif). volume ≤ 0 → UNMEASURABLE. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def impact_bps(order_size: Any, market_volume: Any, *, coef: float = 1.0) -> Any:
    """Impact ≈ coef × (order_size / market_volume)² exprimé en bps. volume ≤ 0/invalide → UNMEASURABLE."""
    if not all(isinstance(x, (int, float)) for x in (order_size, market_volume)) or float(market_volume) <= 0:
        return UNMEASURABLE
    part = abs(float(order_size)) / float(market_volume)
    return round(float(coef) * (part ** 2) * 1e4, 6)


def taille_absurde(order_size: Any, market_volume: Any, *, part_max: float = 0.1, coef: float = 1.0) -> dict[str, Any]:
    """Signale une taille absurde si sa part de volume dépasse part_max (impact challenger explosif).
    volume invalide → absurde présumé (fail-closed : on ne valide pas une taille non mesurable)."""
    if not all(isinstance(x, (int, float)) for x in (order_size, market_volume)) or float(market_volume) <= 0:
        return {"absurde": True, "impact_bps": UNMEASURABLE, "raison": "VOLUME_INVALIDE"}
    part = abs(float(order_size)) / float(market_volume)
    return {"absurde": bool(part > float(part_max)), "part_volume": round(part, 6),
            "impact_bps": impact_bps(order_size, market_volume, coef=coef),
            "raison": ("TAILLE_ABSURDE" if part > float(part_max) else "OK")}


__all__ = ["impact_bps", "taille_absurde", "UNMEASURABLE"]
