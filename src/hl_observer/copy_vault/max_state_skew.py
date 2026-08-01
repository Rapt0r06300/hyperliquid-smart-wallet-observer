"""[COPY-VAULT lot2 #63] MAXIMUM STATE SKEW fill_ts vs snapshot : l'écart temporel MAX toléré entre l'horodatage
d'un fill et celui du snapshot position/equity utilisé pour le dimensionner. Au-delà, l'action est déclarée NON
FIABLE : on dimensionnerait un fill récent avec un état périmé (ou l'inverse). Horodatage inconnu → non fiable.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def fiable(fill_ts_ms: Any, snapshot_ts_ms: Any, *, skew_max_ms: float = 2000.0) -> dict[str, Any]:
    """Fiable seulement si |fill_ts − snapshot_ts| ≤ skew_max. Au-delà → NON FIABLE. Horodatage invalide →
    non fiable (on ne dimensionne pas sur un décalage inconnu)."""
    if not all(isinstance(x, (int, float)) for x in (fill_ts_ms, snapshot_ts_ms)):
        return {"fiable": False, "raison": "HORODATAGE_INCONNU"}
    skew = abs(float(fill_ts_ms) - float(snapshot_ts_ms))
    ok = skew <= float(skew_max_ms)
    return {"fiable": bool(ok), "skew_ms": round(skew, 3), "skew_max_ms": float(skew_max_ms),
            "raison": ("OK" if ok else "SKEW_TROP_GRAND_ACTION_NON_FIABLE")}


__all__ = ["fiable"]
