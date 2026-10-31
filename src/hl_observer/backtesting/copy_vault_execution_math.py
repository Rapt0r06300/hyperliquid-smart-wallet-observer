"""Pure observed-L2 validation and VWAP helpers for Copy-Vault PAPER replay.

This module has no network access, state mutation, fee policy, or execution authority.
It only validates already-recorded depth and walks exactly the visible liquidity.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, localcontext
from functools import lru_cache
from typing import Any

_DECIMAL_PRECISION = 80


class _FallbackToDecimal:
    __slots__ = ()


_FALLBACK_TO_DECIMAL = _FallbackToDecimal()


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
            if any(isinstance(value, bool) for value in raw_level):
                return None
            price, quantity = float(raw_level[0]), float(raw_level[1])
            if not all(math.isfinite(value) for value in (price, quantity)):
                return None
            if price <= 0.0 or quantity <= 0.0:
                return None
            levels.append((price, quantity))
    except (TypeError, ValueError, OverflowError):
        return None
    if isinstance(expected_best, bool):
        return None
    try:
        best_price = float(expected_best)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(best_price) or best_price <= 0 or levels[0][0] != best_price:
        return None
    prices = [price for price, _ in levels]
    ordered = all(
        left >= right if descending else left <= right
        for left, right in zip(prices, prices[1:], strict=False)
    )
    return levels if ordered else None


def _walk_quote_notional(
    levels: list[tuple[float, float]], target_quote_usd: float
) -> tuple[float, float] | None:
    """Return (VWAP, base quantity) after consuming an exact quote notional."""
    target_float = _positive_float(target_quote_usd)
    prepared_levels = _prepared_float_levels(levels)
    if target_float is not None and prepared_levels is not None:
        fast_result = _walk_quote_notional_fast(prepared_levels, target_float)
        if fast_result is not _FALLBACK_TO_DECIMAL:
            return fast_result

    return _walk_quote_notional_decimal(levels, target_quote_usd)


def _walk_quote_notional_decimal(
    levels: list[tuple[float, float]], target_quote_usd: float
) -> tuple[float, float] | None:
    target = _positive_decimal(target_quote_usd)
    decimal_levels = _decimal_levels(levels)
    if target is None or decimal_levels is None:
        return None

    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
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
    target_float = _positive_float(target_quantity)
    prepared_levels = _prepared_float_levels(levels)
    if target_float is not None and prepared_levels is not None:
        fast_result = _walk_base_quantity_fast(prepared_levels, target_float)
        if fast_result is not _FALLBACK_TO_DECIMAL:
            return fast_result

    return _walk_base_quantity_decimal(levels, target_quantity)


def _walk_base_quantity_decimal(
    levels: list[tuple[float, float]], target_quantity: float
) -> float | None:
    target = _positive_decimal(target_quantity)
    decimal_levels = _decimal_levels(levels)
    if target is None or decimal_levels is None:
        return None

    with localcontext() as context:
        context.prec = _DECIMAL_PRECISION
        remaining_quantity = target
        quote_parts: list[Decimal] = []
        for price, available_quantity in decimal_levels:
            taken_quantity = min(remaining_quantity, available_quantity)
            if taken_quantity > 0:
                quote = price * taken_quantity
                if not quote.is_finite() or quote <= 0:
                    return None
                quote_parts.append(quote)
                remaining_quantity -= taken_quantity
            if remaining_quantity == 0:
                break

        if remaining_quantity != 0 or not quote_parts:
            return None
        filled_quote = sum(quote_parts, Decimal(0))
        if not filled_quote.is_finite() or filled_quote <= 0:
            return None
        vwap = float(filled_quote / target)
    return vwap if math.isfinite(vwap) and vwap > 0 else None


def _walk_quote_notional_fast(
    prepared: tuple[
        tuple[tuple[float, float], ...], tuple[float, ...], float, float
    ],
    target: float,
) -> tuple[float, float] | None | _FallbackToDecimal:
    levels, products, quote_capacity, _ = prepared
    if not _capacity_is_safely_sufficient(target, quote_capacity):
        return _FALLBACK_TO_DECIMAL

    remaining = target
    quantity_parts: list[float] = []
    first_price = levels[0][0]
    same_price = True
    for (price, available_quantity), product in zip(levels, products, strict=True):
        if _near_float_boundary(remaining, product):
            return _FALLBACK_TO_DECIMAL
        if remaining >= product:
            quantity_parts.append(available_quantity)
            same_price = same_price and price == first_price
            remaining -= product
            continue

        taken_quantity = remaining / price
        if taken_quantity <= 0 or taken_quantity >= available_quantity:
            return _FALLBACK_TO_DECIMAL
        quantity_parts.append(taken_quantity)
        same_price = same_price and price == first_price
        filled_quantity = math.fsum(quantity_parts)
        vwap = (
            first_price
            if filled_quantity > 0 and same_price
            else target / filled_quantity
            if filled_quantity > 0
            else math.nan
        )
        result = (vwap, filled_quantity)
        if all(math.isfinite(value) and value > 0 for value in result):
            return result
        return _FALLBACK_TO_DECIMAL

    return _FALLBACK_TO_DECIMAL


def _walk_base_quantity_fast(
    prepared: tuple[
        tuple[tuple[float, float], ...], tuple[float, ...], float, float
    ],
    target: float,
) -> float | None | _FallbackToDecimal:
    levels, _, _, base_capacity = prepared
    if not _capacity_is_safely_sufficient(target, base_capacity):
        return _FALLBACK_TO_DECIMAL

    remaining = target
    quote_parts: list[float] = []
    first_price = levels[0][0]
    same_price = True
    for price, available_quantity in levels:
        if _near_float_boundary(remaining, available_quantity):
            return _FALLBACK_TO_DECIMAL
        if remaining >= available_quantity:
            quote_parts.append(price * available_quantity)
            same_price = same_price and price == first_price
            remaining -= available_quantity
            continue

        if remaining < available_quantity:
            taken_quantity = remaining
            if taken_quantity <= 0:
                return _FALLBACK_TO_DECIMAL
            quote_parts.append(price * taken_quantity)
            same_price = same_price and price == first_price
            filled_quote = math.fsum(quote_parts)
            vwap = (
                first_price
                if filled_quote > 0 and same_price
                else filled_quote / target
                if filled_quote > 0
                else math.nan
            )
            return vwap if math.isfinite(vwap) and vwap > 0 else _FALLBACK_TO_DECIMAL

        return _FALLBACK_TO_DECIMAL

    return _FALLBACK_TO_DECIMAL


def _capacity_is_safely_sufficient(target: float, capacity: float) -> bool:
    if not math.isfinite(capacity) or capacity < float.fromhex("0x1.0p-1022"):
        return False
    rounding_guard = capacity * (32.0 * math.ulp(1.0))
    return math.isfinite(rounding_guard) and target < capacity - rounding_guard


def _near_float_boundary(left: float, right: float) -> bool:
    scale = max(abs(left), abs(right))
    return abs(left - right) <= scale * (32.0 * math.ulp(1.0))


def _positive_float(value: object) -> float | None:
    if type(value) is float:
        return value if math.isfinite(value) and value > 0 else None
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(result) or result <= 0:
        return None
    return result


def _prepared_float_levels(
    levels: object,
) -> tuple[tuple[tuple[float, float], ...], tuple[float, ...], float, float] | None:
    if type(levels) is not list or not levels:
        return None
    for level in levels:
        if (
            type(level) is not tuple
            or len(level) != 2
            or type(level[0]) is not float
            or type(level[1]) is not float
            or not math.isfinite(level[0])
            or not math.isfinite(level[1])
            or level[0] <= 0
            or level[1] <= 0
        ):
            return None
    try:
        key = tuple(levels)
    except (TypeError, ValueError):
        return None
    try:
        return _cached_prepared_float_levels(key)
    except TypeError:
        return None


@lru_cache(maxsize=8192)
def _cached_prepared_float_levels(
    levels: tuple[tuple[float, float], ...],
) -> tuple[tuple[tuple[float, float], ...], tuple[float, ...], float, float] | None:
    if not levels:
        return None
    products: list[float] = []
    quantities: list[float] = []
    for level in levels:
        if (
            type(level) is not tuple
            or len(level) != 2
            or type(level[0]) is not float
            or type(level[1]) is not float
        ):
            return None
        price, quantity = level
        if not all(math.isfinite(value) and value > 0 for value in level):
            return None
        product = price * quantity
        if not math.isfinite(product) or product <= 0:
            return None
        products.append(product)
        quantities.append(quantity)
    try:
        quote_capacity = math.fsum(products)
        base_capacity = math.fsum(quantities)
    except (OverflowError, ValueError):
        return None
    if not all(math.isfinite(value) and value > 0 for value in (quote_capacity, base_capacity)):
        return None
    return levels, tuple(products), quote_capacity, base_capacity


def _positive_decimal(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        result = Decimal(str(value))
        float_value = float(result)
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        return None
    if (
        not result.is_finite()
        or result <= 0
        or not math.isfinite(float_value)
        or float_value <= 0
    ):
        return None
    return result


def _decimal_levels(
    levels: object,
) -> list[tuple[Decimal, Decimal]] | None:
    if not isinstance(levels, list) or not levels:
        return None
    normalized: list[tuple[Decimal, Decimal]] = []
    for level in levels:
        if not isinstance(level, (list, tuple)) or len(level) != 2:
            return None
        price = _positive_decimal(level[0])
        quantity = _positive_decimal(level[1])
        if price is None or quantity is None:
            return None
        normalized.append((price, quantity))
    return normalized


__all__ = ["_book_side", "_walk_base_quantity", "_walk_quote_notional"]
