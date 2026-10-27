"""Pure observed-L2 validation and VWAP helpers for Copy-Vault PAPER replay.

This module has no network access, state mutation, fee policy, or execution authority.
It only validates already-recorded depth and walks exactly the visible liquidity.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, localcontext
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
    if isinstance(expected_best, bool):
        return None
    try:
        best = float(expected_best)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(best) or best <= 0.0 or levels[0][0] != best:
        return None
    return levels


def _walk_quote_notional(
    levels: list[tuple[float, float]], target_quote_usd: float
) -> tuple[float, float] | None:
    """Return (VWAP, base quantity) after consuming an exact quote notional."""

    target = _positive_decimal(target_quote_usd)
    decimal_levels = _decimal_levels(levels)
    if target is None or decimal_levels is None:
        return None

    with localcontext() as context:
        context.prec = _precision_for(target, decimal_levels)
        remaining_quote = target
        quantity_parts: list[Decimal] = []
        for price, available_quantity in decimal_levels:
            available_quote = price * available_quantity
            if not available_quote.is_finite() or available_quote <= 0:
                return None
            taken_quote = min(remaining_quote, available_quote)
            if taken_quote > 0:
                taken_quantity = taken_quote / price
                if not taken_quantity.is_finite() or taken_quantity <= 0:
                    return None
                quantity_parts.append(taken_quantity)
                remaining_quote -= taken_quote
            if remaining_quote == 0:
                break
        if remaining_quote != 0 or not quantity_parts:
            return None
        filled_quantity = sum(quantity_parts, Decimal(0))
        if not filled_quantity.is_finite() or filled_quantity <= 0:
            return None
        vwap = target / filled_quantity
        result = float(vwap), float(filled_quantity)
    if not all(math.isfinite(value) and value > 0 for value in result):
        return None
    return result


def _walk_base_quantity(
    levels: list[tuple[float, float]], target_quantity: float
) -> float | None:
    """Return VWAP for an exact base quantity, failing on visible-depth exhaustion."""

    target = _positive_decimal(target_quantity)
    decimal_levels = _decimal_levels(levels)
    if target is None or decimal_levels is None:
        return None
    with localcontext() as context:
        context.prec = _precision_for(target, decimal_levels)
        remaining_quantity = target
        quote_parts: list[Decimal] = []
        for price, available_quantity in decimal_levels:
            taken_quantity = min(remaining_quantity, available_quantity)
            if taken_quantity > 0:
                taken_quote = price * taken_quantity
                if not taken_quote.is_finite() or taken_quote <= 0:
                    return None
                quote_parts.append(taken_quote)
                remaining_quantity -= taken_quantity
            if remaining_quantity == 0:
                break
        if remaining_quantity != 0 or not quote_parts:
            return None
        filled_quote = sum(quote_parts, Decimal(0))
        if not filled_quote.is_finite() or filled_quote <= 0:
            return None
        quote_notional = float(filled_quote)
        if not math.isfinite(quote_notional):
            return None
        vwap = float(filled_quote / target)
    return vwap if math.isfinite(vwap) and vwap > 0 else None


def _positive_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        result = Decimal(str(value))
        as_float = float(result)
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return None
    if (
        not result.is_finite()
        or result <= 0
        or not math.isfinite(as_float)
        or as_float <= 0
    ):
        return None
    return result


def _decimal_levels(
    levels: object,
) -> list[tuple[Decimal, Decimal]] | None:
    if not isinstance(levels, list) or not levels:
        return None
    parsed: list[tuple[Decimal, Decimal]] = []
    for level in levels:
        if not isinstance(level, (list, tuple)) or len(level) != 2:
            return None
        price = _positive_decimal(level[0])
        quantity = _positive_decimal(level[1])
        if price is None or quantity is None:
            return None
        parsed.append((price, quantity))
    return parsed


def _precision_for(
    target: Decimal, levels: list[tuple[Decimal, Decimal]]
) -> int:
    """Keep capacity/sum comparisons exact for finite decimal input strings."""
    product_digits = max(
        len(price.as_tuple().digits) + len(quantity.as_tuple().digits)
        for price, quantity in levels
    )
    target_digits = len(target.as_tuple().digits)
    return max(80, product_digits, target_digits) + len(str(len(levels))) + 4


__all__ = ["_book_side", "_walk_base_quantity", "_walk_quote_notional"]
