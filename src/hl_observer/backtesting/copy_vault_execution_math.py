"""Pure observed-L2 validation and VWAP helpers for Copy-Vault PAPER replay.

This module has no network access, state mutation, fee policy, or execution authority.
It only validates already-recorded depth and walks exactly the visible liquidity.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from hl_observer.normalization.l2_book import normalize_l2_levels


def _book_side(
    book: Mapping[str, Any],
    field: str,
    *,
    expected_best: float,
    descending: bool,
) -> list[tuple[float, float]] | None:
    """Validate one recorded side exactly as observed; never extend its depth."""

    raw_levels = book.get(field)
    normalized = normalize_l2_levels(
        raw_levels, side="bid" if descending else "ask"
    )
    if normalized is None:
        return None
    levels = [(price, quantity) for price, quantity in normalized]
    if not math.isclose(levels[0][0], float(expected_best), abs_tol=1e-12):
        return None
    return levels


def _walk_quote_notional(
    levels: list[tuple[float, float]], target_quote_usd: float
) -> tuple[float, float] | None:
    """Return (VWAP, base quantity) after consuming an exact quote notional."""

    if isinstance(target_quote_usd, bool):
        return None
    try:
        target_quote = float(target_quote_usd)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(target_quote) or target_quote <= 0.0:
        return None
    remaining_quote = target_quote
    filled_quantity = 0.0
    for price, available_quantity in levels:
        available_quote = price * available_quantity
        taken_quote = min(remaining_quote, available_quote)
        filled_quantity += taken_quote / price
        remaining_quote -= taken_quote
        if remaining_quote <= 1e-10:
            break
    roundoff = min(
        math.ulp(target_quote) * (len(levels) + 2),
        target_quote - math.nextafter(target_quote, 0.0),
    )
    if remaining_quote > roundoff or filled_quantity <= 0.0:
        return None
    return target_quote / filled_quantity, filled_quantity


def _walk_base_quantity(
    levels: list[tuple[float, float]], target_quantity: float
) -> float | None:
    """Return VWAP for an exact base quantity, failing on visible-depth exhaustion."""

    if isinstance(target_quantity, bool):
        return None
    try:
        target = float(target_quantity)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(target) or target <= 0.0:
        return None
    remaining_quantity = target
    filled_quote = 0.0
    for price, available_quantity in levels:
        taken_quantity = min(remaining_quantity, available_quantity)
        taken_quote = price * taken_quantity
        if not math.isfinite(taken_quote):
            return None
        filled_quote += taken_quote
        if not math.isfinite(filled_quote):
            return None
        remaining_quantity -= taken_quantity
        if remaining_quantity <= 1e-12:
            break
    roundoff = min(
        math.ulp(target) * (len(levels) + 2),
        target - math.nextafter(target, 0.0),
    )
    if remaining_quantity > roundoff or filled_quote <= 0.0:
        return None
    vwap = filled_quote / target
    return vwap if math.isfinite(vwap) and vwap > 0.0 else None


__all__ = ["_book_side", "_walk_base_quantity", "_walk_quote_notional"]
