"""Conservative decimal helpers for Copy-Vault economic evidence."""

from __future__ import annotations

import math
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation, localcontext

USD_RECONCILIATION_ABS_TOLERANCE = Decimal("0.00000001")


def decimal_value(value: object) -> Decimal | None:
    """Parse finite numeric evidence without accepting booleans as money."""
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if result.is_finite() else None


def decimal_sum(values: Iterable[object]) -> Decimal | None:
    """Sum finite values without context rounding, or reject the whole sum."""
    parsed: list[Decimal] = []
    for value in values:
        number = decimal_value(value)
        if number is None:
            return None
        parsed.append(number)
    if not parsed:
        return Decimal(0)
    precision = _sum_precision(parsed)
    with localcontext() as context:
        context.prec = precision
        return sum(parsed, Decimal(0))


def float_not_above(value: Decimal) -> float | None:
    """Convert Decimal to float while never rounding PnL upward."""
    return _conservative_float(value, upward=False)


def float_not_below(value: Decimal) -> float | None:
    """Convert Decimal to float while never rounding a cost/risk downward."""
    return _conservative_float(value, upward=True)


def _conservative_float(value: Decimal, *, upward: bool) -> float | None:
    if not isinstance(value, Decimal) or not value.is_finite():
        return None
    try:
        converted = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(converted):
        return None
    converted_decimal = Decimal(str(converted))
    if upward and converted_decimal < value:
        converted = math.nextafter(converted, math.inf)
    elif not upward and converted_decimal > value:
        converted = math.nextafter(converted, -math.inf)
    return converted if math.isfinite(converted) else None


def _sum_precision(values: list[Decimal]) -> int:
    nonzero = [value for value in values if value]
    if not nonzero:
        return 28
    highest = max(value.adjusted() for value in nonzero)
    lowest = min(value.as_tuple().exponent for value in nonzero)
    return max(28, highest - lowest + len(str(len(values))) + 3)
