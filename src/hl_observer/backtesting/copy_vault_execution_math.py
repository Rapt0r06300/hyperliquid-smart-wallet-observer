"""Pure observed-L2 validation and VWAP helpers for Copy-Vault PAPER replay.

This module has no network access, state mutation, fee policy, or execution authority.
It only validates already-recorded depth and walks exactly the visible liquidity.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any


def _book_side(
    book: Mapping[str, Any],
    field: str,
    *,
    expected_best: float,
    descending: bool,
) -> list[tuple[float, float]] | None:
    """Validate one recorded side exactly as observed; never extend its depth."""

    raw_levels = book.get(field)
    if not isinstance(raw_levels, list) or not raw_levels:
        return None
    levels: list[tuple[float, float]] = []
    try:
        for raw_level in raw_levels:
            if not isinstance(raw_level, (list, tuple)) or len(raw_level) != 2:
                return None
            price, quantity = float(raw_level[0]), float(raw_level[1])
            if not all(math.isfinite(value) for value in (price, quantity)):
                return None
            if price <= 0.0 or quantity <= 0.0:
                return None
            levels.append((price, quantity))
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isclose(levels[0][0], float(expected_best), abs_tol=1e-12):
        return None
    prices = [price for price, _ in levels]
    ordered = all(
        left >= right if descending else left <= right
        for left, right in zip(prices, prices[1:])
    )
    return levels if ordered else None


def _walk_quote_notional(
    levels: list[tuple[float, float]], target_quote_usd: float
) -> tuple[float, float] | None:
    """Return (VWAP, base quantity) after consuming an exact quote notional."""

    remaining_quote = float(target_quote_usd)
    filled_quantity = 0.0
    for price, available_quantity in levels:
        available_quote = price * available_quantity
        taken_quote = min(remaining_quote, available_quote)
        filled_quantity += taken_quote / price
        remaining_quote -= taken_quote
        if remaining_quote <= 1e-10:
            break
    if remaining_quote > 1e-8 or filled_quantity <= 0.0:
        return None
    return float(target_quote_usd) / filled_quantity, filled_quantity


def _walk_base_quantity(
    levels: list[tuple[float, float]], target_quantity: float
) -> float | None:
    """Return VWAP for an exact base quantity, failing on visible-depth exhaustion."""

    remaining_quantity = float(target_quantity)
    filled_quote = 0.0
    for price, available_quantity in levels:
        taken_quantity = min(remaining_quantity, available_quantity)
        filled_quote += price * taken_quantity
        remaining_quantity -= taken_quantity
        if remaining_quantity <= 1e-12:
            break
    if remaining_quantity > 1e-10 or target_quantity <= 0.0:
        return None
    return filled_quote / float(target_quantity)


__all__ = ["_book_side", "_walk_base_quantity", "_walk_quote_notional"]
