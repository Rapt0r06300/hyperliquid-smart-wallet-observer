from __future__ import annotations

import math


def liquidity_ok(orderbook_depth_usdc: float, min_depth_usdc: float) -> bool:
    """Fail closed when liquidity evidence or its configured floor is invalid."""
    try:
        depth = float(orderbook_depth_usdc)
        minimum = float(min_depth_usdc)
    except (TypeError, ValueError):
        return False
    return math.isfinite(depth) and math.isfinite(minimum) and depth >= 0.0 and minimum >= 0.0 and depth >= minimum
