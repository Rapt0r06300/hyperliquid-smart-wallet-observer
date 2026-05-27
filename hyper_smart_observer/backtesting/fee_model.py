from __future__ import annotations

from hyper_smart_observer.paper_trading.fees import calculate_fee


def backtest_fee(notional: float, fee_rate_bps: float) -> float:
    return calculate_fee(notional, fee_rate_bps)
