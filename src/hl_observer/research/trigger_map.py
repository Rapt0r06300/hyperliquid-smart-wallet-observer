"""ALPHA P29 — CARTE des TRIGGERS / TP-SL (si L4/order status). SHADOW uniquement.

Si les statuts d'ordre exposent isTrigger / triggerPx / isPositionTpsl / children / reduceOnly, on cartographie
la DENSITÉ de triggers par niveau de prix : une zone dense de stops peut accélérer (cascade) ou absorber le
prix. On teste accélération / absorption / reversal autour de ces zones. SHADOW jusqu'à preuve.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

BLOCKED = "BLOCKED_EXTERNAL"


def densite_triggers(triggers: Sequence[Mapping[str, Any]], *, mid: float, bucket_bps: float = 10.0) -> dict[str, Any]:
    """Densité de triggers par bucket de distance au mid (bps). Chaque trigger : {triggerPx, size, reduceOnly}."""
    if not triggers or mid <= 0:
        return {"buckets": {}, "zone_dense_bps": None}
    par_bucket: dict[int, float] = {}
    for t in triggers:
        px = t.get("triggerPx")
        if not isinstance(px, (int, float)):
            continue
        dist_bps = (px - mid) / mid * 1e4
        b = int(dist_bps // bucket_bps)
        par_bucket[b] = par_bucket.get(b, 0.0) + float(t.get("size", 1.0))
    if not par_bucket:
        return {"buckets": {}, "zone_dense_bps": None}
    zone = max(par_bucket, key=lambda b: par_bucket[b])
    return {"buckets": {int(k * bucket_bps): round(v, 4) for k, v in sorted(par_bucket.items())},
            "zone_dense_bps": int(zone * bucket_bps), "taille_zone_dense": round(par_bucket[zone], 4)}


def flux_l4() -> dict[str, Any]:
    return {"statut": BLOCKED, "manque": "statuts d'ordre L4 (isTrigger/triggerPx/isPositionTpsl) cote user"}


__all__ = ["densite_triggers", "flux_l4", "BLOCKED"]
