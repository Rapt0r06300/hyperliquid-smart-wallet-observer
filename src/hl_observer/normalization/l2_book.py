"""Fail-closed normalization for observed L2 price levels."""
from __future__ import annotations

import math
from typing import Any, Literal


def normalize_l2_levels(
    value: Any, *, side: Literal["bid", "ask"]
) -> list[list[float]] | None:
    """Convert one observed side while preserving and validating source order.

    Bids must be strictly descending and asks strictly ascending. Strict order
    also rejects duplicate prices. The function never repairs a book by sorting.
    """

    if side not in {"bid", "ask"} or not isinstance(value, list) or not value:
        return None
    levels: list[list[float]] = []
    previous_price: float | None = None
    try:
        for raw_level in value:
            if not isinstance(raw_level, (list, tuple)) or len(raw_level) != 2:
                return None
            if isinstance(raw_level[0], bool) or isinstance(raw_level[1], bool):
                return None
            price, quantity = float(raw_level[0]), float(raw_level[1])
            if not math.isfinite(price) or not math.isfinite(quantity):
                return None
            if price <= 0.0 or quantity <= 0.0:
                return None
            if previous_price is not None:
                if side == "bid" and price >= previous_price:
                    return None
                if side == "ask" and price <= previous_price:
                    return None
            levels.append([price, quantity])
            previous_price = price
    except (TypeError, ValueError, OverflowError):
        return None
    return levels


def validate_l2_book_sides(
    bids_value: Any, asks_value: Any, *, bid: Any, ask: Any
) -> tuple[tuple[list[list[float]], list[list[float]]] | None, str | None]:
    """Validate both observed sides and their exact binding to the recorded BBO."""

    if isinstance(bid, bool) or isinstance(ask, bool):
        return None, "L2_BBO_INVALID"
    try:
        best_bid, best_ask = float(bid), float(ask)
    except (TypeError, ValueError, OverflowError):
        return None, "L2_BBO_INVALID"
    if not math.isfinite(best_bid) or not math.isfinite(best_ask):
        return None, "L2_BBO_INVALID"
    bids = normalize_l2_levels(bids_value, side="bid")
    if bids is None:
        return None, "L2_BIDS_INVALID_ORDER_OR_VALUE"
    asks = normalize_l2_levels(asks_value, side="ask")
    if asks is None:
        return None, "L2_ASKS_INVALID_ORDER_OR_VALUE"
    if bids[0][0] >= asks[0][0]:
        return None, "L2_BOOK_CROSSED"
    if best_bid >= best_ask:
        return None, "L2_BBO_CROSSED"
    if bids[0][0] != best_bid or asks[0][0] != best_ask:
        return None, "L2_BBO_MISMATCH"
    return (bids, asks), None
