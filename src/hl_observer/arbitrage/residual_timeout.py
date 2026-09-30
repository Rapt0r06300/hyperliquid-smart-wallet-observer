"""[ARB #42] RESIDUAL TIMEOUT : une position déséquilibrée (jambe orpheline) a une DURÉE DE VIE MAXIMALE avant
liquidation paper forcée, INDÉPENDAMMENT de l'edge initial. « L'arb était beau » n'est pas une raison de garder
un résidu nu indéfiniment : plus il dure, plus le gap-risk s'accumule. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any

CONSERVER = "CONSERVER"
LIQUIDER_PAPER = "LIQUIDER_PAPER"


def evaluer(ouvert_ms: Any, now_ms: Any, *, ttl_ms: float) -> dict[str, Any]:
    """Au-delà de ttl_ms depuis l'ouverture du résidu → LIQUIDER_PAPER (forcé). Horodatage inconnu →
    LIQUIDER_PAPER par prudence (on ne laisse pas courir un résidu au suivi incertain)."""
    if not all(isinstance(x, (int, float)) for x in (ouvert_ms, now_ms)):
        return {"action": LIQUIDER_PAPER, "raison": "HORODATAGE_INCONNU", "age_ms": None}
    age = float(now_ms) - float(ouvert_ms)
    if age >= float(ttl_ms):
        return {"action": LIQUIDER_PAPER, "raison": "RESIDU_TROP_VIEUX", "age_ms": round(age, 3)}
    return {"action": CONSERVER, "raison": "DANS_LE_TTL", "age_ms": round(age, 3),
            "reste_ms": round(float(ttl_ms) - age, 3)}


__all__ = ["evaluer", "CONSERVER", "LIQUIDER_PAPER"]
