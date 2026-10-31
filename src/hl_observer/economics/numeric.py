"""Decimal helpers shared by authoritative economic proof paths."""

from __future__ import annotations

import math
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation

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
    total = Decimal(0)
    for value in values:
        number = decimal_value(value)
        if number is None:
            return None
        total += number
    return total


def float_not_above(value: Decimal) -> float | None:
    """Convert Decimal to float while never rounding PnL upward."""

    converted = float(value)
    if not math.isfinite(converted):
        return None
    if Decimal(str(converted)) > value:
        converted = math.nextafter(converted, -math.inf)
    return converted if math.isfinite(converted) else None


def float_not_below(value: Decimal) -> float | None:
    """Convert Decimal to float while never rounding a cost/risk value downward."""

    converted = float(value)
    if not math.isfinite(converted):
        return None
    if Decimal(str(converted)) < value:
        converted = math.nextafter(converted, math.inf)
    return converted if math.isfinite(converted) else None
