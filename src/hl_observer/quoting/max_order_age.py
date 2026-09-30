"""[CROSS-VENUE lot2 #77] max_order_age INDÉPENDANT du refresh prix : même un prix encore acceptable ne doit pas
laisser une quote vivre éternellement. Un ordre trop vieux accumule du risque d'adverse selection ; son expiration
est décidée par un âge maximal PROPRE, distinct du cycle de refresh de prix (Hummingbot distingue les deux).
Horodatage inconnu → expiré (prudence). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def expire(pose_ms: Any, now_ms: Any, *, max_age_ms: float) -> dict[str, Any]:
    """Expire dès que l'âge dépasse max_age_ms, INDÉPENDAMMENT du fait que le prix soit encore bon. Horodatage
    invalide → expiré."""
    if not all(isinstance(x, (int, float)) for x in (pose_ms, now_ms)):
        return {"expire": True, "raison": "HORODATAGE_INCONNU"}
    age = float(now_ms) - float(pose_ms)
    if age >= float(max_age_ms):
        return {"expire": True, "age_ms": round(age, 3), "raison": "MAX_ORDER_AGE_ATTEINT"}
    return {"expire": False, "age_ms": round(age, 3), "reste_ms": round(float(max_age_ms) - age, 3)}


__all__ = ["expire"]
