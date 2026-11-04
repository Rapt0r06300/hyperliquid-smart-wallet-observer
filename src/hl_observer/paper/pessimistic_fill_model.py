from __future__ import annotations

import math


def pessimistic_fill_price(side: str, observed_price: float, spread_bps: float, slippage_bps: float) -> float:
    if observed_price <= 0:
        raise ValueError("observed_price must be positive")
    cost_multiplier = 1.0 + (spread_bps + slippage_bps) / 10000.0
    if side.lower() in {"buy", "long"}:
        return observed_price * cost_multiplier
    return observed_price / cost_multiplier


def touch_only_fill_receipt(*, side: object, touched: object, observed_price: object, spread_bps: object, slippage_bps: object) -> dict[str, object]:
    """Never turn a price touch into a fill without an observed execution price."""

    if not isinstance(touched, bool) or not isinstance(side, str) or side.upper() not in {"BUY", "SELL", "LONG", "SHORT"}:
        return {"status": "UNMEASURABLE", "filled": False, "reason": "INPUT_INVALID"}
    try:
        price, spread, slip = float(observed_price), float(spread_bps), float(slippage_bps)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "filled": False, "reason": "PRICE_OR_COST_INVALID"}
    if not all(math.isfinite(value) and value >= 0.0 for value in (price, spread, slip)) or price <= 0.0:
        return {"status": "UNMEASURABLE", "filled": False, "reason": "PRICE_OR_COST_INVALID"}
    return {"status": "PROVEN", "filled": False, "reason": "TOUCH_IS_NOT_FILL" if touched else "NO_TOUCH"}
