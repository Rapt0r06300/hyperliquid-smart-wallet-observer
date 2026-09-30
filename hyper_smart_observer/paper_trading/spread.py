from __future__ import annotations


def apply_spread(reference_price: float, side: str, spread_bps: float) -> float:
    if reference_price <= 0:
        raise ValueError("reference_price must be positive")
    if spread_bps < 0:
        raise ValueError("spread_bps must be non-negative")
    normalized_side = side.upper()
    half_spread = spread_bps / 20_000.0
    if normalized_side == "BUY":
        return reference_price * (1.0 + half_spread)
    if normalized_side == "SELL":
        return reference_price * (1.0 - half_spread)
    raise ValueError("side must be BUY or SELL")
