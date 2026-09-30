from __future__ import annotations


def pessimistic_fill_price(side: str, observed_price: float, spread_bps: float, slippage_bps: float) -> float:
    if observed_price <= 0:
        raise ValueError("observed_price must be positive")
    cost_multiplier = 1.0 + (spread_bps + slippage_bps) / 10000.0
    if side.lower() in {"buy", "long"}:
        return observed_price * cost_multiplier
    return observed_price / cost_multiplier
