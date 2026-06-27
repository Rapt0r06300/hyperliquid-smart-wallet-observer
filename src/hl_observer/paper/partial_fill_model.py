from __future__ import annotations


def partial_fill_ratio(order_notional_usdc: float, orderbook_depth_usdc: float) -> float:
    if order_notional_usdc <= 0:
        return 0.0
    if orderbook_depth_usdc <= 0:
        return 0.0
    return min(1.0, orderbook_depth_usdc / order_notional_usdc)
