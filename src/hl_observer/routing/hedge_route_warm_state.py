"""[ARB pépite 236] HEDGE ROUTE WARM-STATE : garder le BBO/depth/state FRAIS sur la route SECONDAIRE même quand elle
n'est pas utilisée. Si le secours n'est réveillé qu'au moment où on en a besoin, son état est froid/périmé et le
basculement est lent et aveugle. On maintient la fraîcheur ; une route dont l'état dépasse un TTL n'est plus « warm »
et ne peut pas servir de secours immédiat. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def est_warm(age_etat_ms: Any, *, ttl_warm_ms: float = 2000.0) -> dict[str, Any]:
    """La route secondaire est 'warm' seulement si son état a été rafraîchi depuis ≤ ttl_warm_ms. Âge inconnu →
    froide (on ne bascule pas vers un secours dont on ignore la fraîcheur)."""
    if not isinstance(age_etat_ms, (int, float)) or float(age_etat_ms) < 0:
        return {"warm": False, "raison": "AGE_ETAT_INCONNU"}
    ok = float(age_etat_ms) <= float(ttl_warm_ms)
    return {"warm": bool(ok), "age_ms": float(age_etat_ms), "ttl_warm_ms": float(ttl_warm_ms),
            "raison": ("OK" if ok else "ETAT_SECONDAIRE_FROID")}


__all__ = ["est_warm"]
