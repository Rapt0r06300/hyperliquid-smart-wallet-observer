"""MARKET-2 — Seuils par classe de marché (fini le one-size-fits-all).

BTC et un memecoin n'ont pas les mêmes edge/liquidité/taille minimum requis. On
classe par profondeur L2 + volume, et on adapte les seuils. Les pertes MON/LIT/
KBONK étaient le symptôme du seuil unique. Pur.
"""

from __future__ import annotations

MAJOR, MID, LONG_TAIL = "MAJOR", "MID", "LONG_TAIL"

_THRESHOLDS = {
    MAJOR:     {"min_edge_bps": 22.0, "min_liquidity_score": 0.55, "min_notional_usdt": 40.0, "max_notional_usdt": 60.0},
    MID:       {"min_edge_bps": 30.0, "min_liquidity_score": 0.45, "min_notional_usdt": 25.0, "max_notional_usdt": 40.0},
    LONG_TAIL: {"min_edge_bps": 45.0, "min_liquidity_score": 0.35, "min_notional_usdt": 15.0, "max_notional_usdt": 25.0},
}


def classify_market(*, l2_depth_usdt: float, daily_volume_usdt: float) -> str:
    d = float(l2_depth_usdt or 0.0)
    v = float(daily_volume_usdt or 0.0)
    if d >= 250_000 and v >= 50_000_000:
        return MAJOR
    if d >= 40_000 and v >= 2_000_000:
        return MID
    return LONG_TAIL


def thresholds_for(market_class: str) -> dict:
    return dict(_THRESHOLDS.get(market_class, _THRESHOLDS[LONG_TAIL]))


def thresholds_for_market(*, l2_depth_usdt: float, daily_volume_usdt: float) -> dict:
    cls = classify_market(l2_depth_usdt=l2_depth_usdt, daily_volume_usdt=daily_volume_usdt)
    out = thresholds_for(cls)
    out["market_class"] = cls
    return out


__all__ = ["MAJOR", "MID", "LONG_TAIL", "classify_market", "thresholds_for", "thresholds_for_market"]
