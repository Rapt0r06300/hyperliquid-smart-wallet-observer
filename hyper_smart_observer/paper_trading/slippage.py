from __future__ import annotations


def estimate_slippage(price: float, slippage_bps: float = 5.0) -> float:
    return price * (slippage_bps / 10_000.0)


def apply_slippage(price: float, side: str, slippage_bps: float) -> float:
    if price <= 0:
        raise ValueError("price must be positive")
    if slippage_bps < 0:
        raise ValueError("slippage_bps must be non-negative")
    normalized_side = side.upper()
    adjustment = slippage_bps / 10_000.0
    if normalized_side == "BUY":
        return price * (1.0 + adjustment)
    if normalized_side == "SELL":
        return price * (1.0 - adjustment)
    raise ValueError("side must be BUY or SELL")
