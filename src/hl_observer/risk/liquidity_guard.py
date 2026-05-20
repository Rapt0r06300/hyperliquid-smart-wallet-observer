from __future__ import annotations


def liquidity_ok(orderbook_depth_usdc: float, min_depth_usdc: float) -> bool:
    return orderbook_depth_usdc >= min_depth_usdc
