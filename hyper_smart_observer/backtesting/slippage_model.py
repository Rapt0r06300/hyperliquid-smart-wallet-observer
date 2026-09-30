from __future__ import annotations

from hyper_smart_observer.paper_trading.slippage import apply_slippage


def backtest_slippage(price: float, side: str, slippage_bps: float) -> float:
    return apply_slippage(price, side, slippage_bps)
