"""[CROSS-VENUE lot2 #74] FILLED-ORDER DELAY : après un fill maker, EMPÊCHER la recréation instantanée d'un ordre
équivalent pendant une courte durée. Reposter immédiatement au même niveau après un fill, c'est souvent se faire
re-remplir par le même flux toxique qui vient de nous prendre — un court délai laisse le marché se stabiliser
(Hummingbot expose ce paramètre `filled_order_delay`). Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def peut_recreer(fill_ts_ms: Any, now_ms: Any, *, delai_ms: float = 1000.0) -> dict[str, Any]:
    """Autorise la recréation d'un ordre équivalent seulement si le délai depuis le fill est écoulé. Horodatage
    inconnu → interdit (prudence : on ne repost pas juste après un fill possiblement toxique)."""
    if not all(isinstance(x, (int, float)) for x in (fill_ts_ms, now_ms)):
        return {"peut_recreer": False, "raison": "HORODATAGE_INCONNU"}
    ecoule = float(now_ms) - float(fill_ts_ms)
    ok = ecoule >= float(delai_ms)
    return {"peut_recreer": bool(ok), "ecoule_ms": round(ecoule, 3), "delai_ms": float(delai_ms),
            "raison": ("OK" if ok else "DELAI_POST_FILL_NON_ECOULE")}


__all__ = ["peut_recreer"]
