from __future__ import annotations

from typing import Any

from hl_observer.markets.spread import safe_float


def calculate_orderbook_depth_usdc(book: dict[str, Any], levels_count: int = 10) -> float | None:
    levels = book.get("levels")
    if not isinstance(levels, list) or len(levels) < 2:
        return None
    bids = levels[0] if isinstance(levels[0], list) else []
    asks = levels[1] if isinstance(levels[1], list) else []
    depth = 0.0
    for side in (bids[:levels_count], asks[:levels_count]):
        for level in side:
            if not isinstance(level, dict):
                continue
            price = safe_float(level.get("px")) or 0.0
            size = safe_float(level.get("sz")) or 0.0
            depth += price * size
    return depth


def liquidity_score(depth_usdc: float | None, min_depth_usdc: float) -> float:
    if depth_usdc is None or depth_usdc <= 0:
        return 0.0
    if min_depth_usdc <= 0:
        return 100.0
    return max(0.0, min(100.0, depth_usdc / min_depth_usdc * 100.0))


def is_liquid(depth_usdc: float | None, min_depth_usdc: float) -> bool:
    if depth_usdc is None:
        return False
    return depth_usdc >= min_depth_usdc

