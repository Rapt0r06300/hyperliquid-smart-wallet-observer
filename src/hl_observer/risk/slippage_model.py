from __future__ import annotations


def estimate_slippage_bps(*, notional_usdc: float, depth_usdc: float) -> float:
    if depth_usdc <= 0:
        return 10_000.0
    return min(10_000.0, notional_usdc / depth_usdc * 10_000.0)
