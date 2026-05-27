from __future__ import annotations

from typing import Any


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def best_bid_ask(book: dict[str, Any]) -> tuple[float | None, float | None]:
    levels = book.get("levels")
    if not isinstance(levels, list) or len(levels) < 2:
        return None, None
    bids = levels[0] if isinstance(levels[0], list) else []
    asks = levels[1] if isinstance(levels[1], list) else []
    best_bid = safe_float(bids[0].get("px")) if bids and isinstance(bids[0], dict) else None
    best_ask = safe_float(asks[0].get("px")) if asks and isinstance(asks[0], dict) else None
    return best_bid, best_ask


def calculate_spread_bps(book: dict[str, Any]) -> float | None:
    best_bid, best_ask = best_bid_ask(book)
    if best_bid is None or best_ask is None or best_bid <= 0 or best_ask <= 0:
        return None
    mid = (best_bid + best_ask) / 2
    if mid <= 0:
        return None
    return (best_ask - best_bid) / mid * 10000


def spread_is_scannable(spread_bps: float | None, max_spread_bps: float) -> bool:
    if spread_bps is None:
        return False
    return spread_bps <= max_spread_bps

