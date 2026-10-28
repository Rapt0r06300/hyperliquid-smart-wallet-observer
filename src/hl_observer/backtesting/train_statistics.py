"""Conservative TRAIN-only statistics shared by economic vNext research.

Selection helpers in this module never know validation/OOS/forward labels.  They
summarise only caller-supplied TRAIN rows and apply a one-sided Bonferroni lower
confidence bound over daily net PnL so a broad research grid cannot win merely
because many variants were tried.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal, localcontext
from fractions import Fraction
from functools import lru_cache
from typing import Any

from hl_observer.economics.numeric import (
    decimal_difference,
    decimal_sum,
    decimal_value,
    float_not_above,
    float_not_below,
)

SCHEMA_VERSION = "hypersmart.train_selection_statistics.v3"
UTC_DAY_MS = 86_400_000
LCB_DECIMAL_PRECISION = 80
NORMAL_TAIL_COEFFICIENT_UPPER_BOUND = Decimal("0.41")
NORMAL_CRITICAL_Z_SEARCH_UPPER_BOUND = Decimal("8")


def _normal_tail_upper_bound(z: Decimal) -> Decimal | None:
    """Return a Decimal upper enclosure for P[N(0,1) <= -z], z > 0.

    Mills' inequality gives tail(z) < exp(-z²/2)/(sqrt(2*pi)*z).
    Since pi > 3 and 0.41² * 6 > 1, 1/sqrt(2*pi) < 0.41.
    Decimal.exp is correctly rounded; the exponent and result are widened
    outwards before the remaining operations are rounded toward +infinity.
    """
    if not isinstance(z, Decimal) or not z.is_finite() or z <= 0:
        return None
    with localcontext() as context:
        context.prec = LCB_DECIMAL_PRECISION
        context.rounding = ROUND_FLOOR
        z_squared_lower = z * z
        context.rounding = ROUND_CEILING
        exponent_upper = z_squared_lower.copy_negate() / Decimal(2)
        exp_nearest = exponent_upper.exp()
        exp_upper = context.next_plus(exp_nearest)
        numerator_upper = NORMAL_TAIL_COEFFICIENT_UPPER_BOUND * exp_upper
        return numerator_upper / z


@lru_cache(maxsize=512)
def _certified_normal_critical_value_upper_bound(alpha: float) -> Decimal:
    """Find a conservative Decimal z whose certified normal tail is <= alpha.

    The bisection is only an efficiency choice. Every returned endpoint is
    accepted only after an outward-rounded Mills bound proves the tail claim.
    """
    if not math.isfinite(alpha) or not 0 < alpha < 0.5:
        raise ValueError("alpha must be finite and strictly between zero and 0.5")
    alpha_exact = Decimal.from_float(alpha)
    low = Decimal(0)
    high = NORMAL_CRITICAL_Z_SEARCH_UPPER_BOUND
    high_tail = _normal_tail_upper_bound(high)
    if high_tail is None or high_tail > alpha_exact:
        raise ArithmeticError("could not certify the normal critical-value bracket")
    with localcontext() as context:
        context.prec = LCB_DECIMAL_PRECISION
        for _ in range(512):
            midpoint = (low + high) / Decimal(2)
            if midpoint in (low, high):
                break
            tail_upper = _normal_tail_upper_bound(midpoint)
            if tail_upper is not None and tail_upper <= alpha_exact:
                high = midpoint
            else:
                low = midpoint
    # Recheck the serialized endpoint itself after leaving the bisection.
    final_tail_upper = _normal_tail_upper_bound(high)
    if final_tail_upper is None or final_tail_upper > alpha_exact:
        raise ArithmeticError("normal critical-value upper bound failed verification")
    return high


def _fraction_decimal_interval(value: Fraction) -> tuple[Decimal, Decimal]:
    """Convert an exact rational to enclosing 80-digit Decimal endpoints."""
    numerator = Decimal(value.numerator)
    denominator = Decimal(value.denominator)
    with localcontext() as context:
        context.prec = LCB_DECIMAL_PRECISION
        context.rounding = ROUND_FLOOR
        lower = numerator / denominator
    with localcontext() as context:
        context.prec = LCB_DECIMAL_PRECISION
        context.rounding = ROUND_CEILING
        upper = numerator / denominator
    return lower, upper


def _sqrt_decimal_interval(
    radicand_lower: Decimal, radicand_upper: Decimal
) -> tuple[Decimal, Decimal]:
    """Enclose square root using correctly-rounded Decimal.sqrt and adjacent ulps."""
    if radicand_lower < 0 or radicand_upper < radicand_lower:
        raise ValueError("invalid nonnegative radicand interval")
    with localcontext() as context:
        context.prec = LCB_DECIMAL_PRECISION
        lower_nearest = radicand_lower.sqrt()
        lower = max(Decimal(0), context.next_minus(lower_nearest))
        upper_nearest = radicand_upper.sqrt()
        upper = context.next_plus(upper_nearest)
    return lower, upper


def _lcb_rounding_interval(
    daily_values: list[Decimal], z_upper: Decimal
) -> tuple[Decimal, Decimal]:
    """Enclose the exact LCB arithmetic over exact Decimal daily observations.

    For n daily values x_i, n*SE = sqrt(n * sum((x_i - mean)^2)/(n-1)).
    The mean/variance radicand are computed as exact rationals; only conversion
    and square root use Decimal, with directed enclosures at every boundary.
    """
    count = len(daily_values)
    if count < 2:
        raise ValueError("at least two daily values are required")
    exact = [Fraction(value) for value in daily_values]
    total = sum(exact, Fraction(0))
    mean = total / count
    squared_deviations = sum(((value - mean) ** 2 for value in exact), Fraction(0))
    radicand = squared_deviations * count / (count - 1)
    total_lower, total_upper = _fraction_decimal_interval(total)
    radicand_lower, radicand_upper = _fraction_decimal_interval(radicand)
    root_lower, root_upper = _sqrt_decimal_interval(radicand_lower, radicand_upper)
    with localcontext() as context:
        context.prec = LCB_DECIMAL_PRECISION
        context.rounding = ROUND_CEILING
        penalty_upper = z_upper * root_upper
    with localcontext() as context:
        context.prec = LCB_DECIMAL_PRECISION
        context.rounding = ROUND_FLOOR
        lower = total_lower - penalty_upper
    with localcontext() as context:
        context.prec = LCB_DECIMAL_PRECISION
        context.rounding = ROUND_FLOOR
        penalty_lower = z_upper * root_lower
    with localcontext() as context:
        context.prec = LCB_DECIMAL_PRECISION
        context.rounding = ROUND_CEILING
        upper = total_upper - penalty_lower
    if upper < lower:
        raise ArithmeticError("outward LCB interval is inverted")
    return lower, upper


def number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def profit_factor_exact(values: Iterable[object]) -> Decimal | None:
    rows = [value for item in values if (value := decimal_value(item)) is not None]
    wins = decimal_sum(value for value in rows if value > 0)
    losses = decimal_sum(value.copy_abs() for value in rows if value < 0)
    if wins is None or losses is None:
        return None
    if losses == 0:
        return None
    with localcontext() as context:
        context.prec = LCB_DECIMAL_PRECISION
        context.rounding = ROUND_FLOOR
        return wins / losses


def profit_factor(values: Iterable[float]) -> float | None:
    exact = profit_factor_exact(values)
    return float_not_above(exact) if exact is not None else None


def top_positive_share(values: Iterable[float]) -> float:
    positives = [
        value
        for item in values
        if (value := decimal_value(item)) is not None and value > 0
    ]
    total = decimal_sum(positives)
    if total is None or total <= 0:
        return 1.0
    with localcontext() as context:
        context.prec = 80
        context.rounding = ROUND_CEILING
        share = max(positives) / total
    converted = float_not_below(share)
    return converted if converted is not None else 1.0


def top_positive_share_within_limit(
    statistics: Mapping[str, Any], threshold: object
) -> bool:
    """Compare concentration as exact positive-PnL ratios, not display floats."""
    largest = decimal_value(
        statistics.get("largest_positive_trade_pnl_usd_exact_decimal")
    )
    total = decimal_value(
        statistics.get("total_positive_trade_pnl_usd_exact_decimal")
    )
    limit = decimal_value(threshold)
    if (
        largest is None
        or total is None
        or limit is None
        or largest <= 0
        or total <= 0
        or largest > total
        or limit < 0
        or limit > 1
    ):
        return False
    largest_numerator, largest_denominator = largest.as_integer_ratio()
    total_numerator, total_denominator = total.as_integer_ratio()
    limit_numerator, limit_denominator = limit.as_integer_ratio()
    return (
        largest_numerator * total_denominator * limit_denominator
        <= total_numerator * largest_denominator * limit_numerator
    )


def exact_net_rank_value(statistics: Mapping[str, Any]) -> Decimal:
    """Return an exact, presentation-independent net PnL tie-break value."""
    exact = decimal_value(statistics.get("net_pnl_usd_exact_decimal"))
    if exact is not None:
        return exact
    legacy = decimal_value(statistics.get("net_pnl_usd"))
    return legacy if legacy is not None else Decimal("-Infinity")


def exact_lcb_rank_value(statistics: Mapping[str, Any]) -> Decimal:
    """Return the conservative Decimal LCB used for candidate comparisons."""
    exact = decimal_value(statistics.get("total_lcb_usd_exact_decimal"))
    if exact is not None:
        return exact
    legacy = decimal_value(statistics.get("total_lcb_usd"))
    return legacy if legacy is not None else Decimal("-Infinity")


def lcb_rank_is_numerically_resolved(
    left: Mapping[str, Any], right: Mapping[str, Any]
) -> bool:
    """Require the LCB gap to exceed recorded uncertainty when values differ."""
    left_lcb = exact_lcb_rank_value(left)
    right_lcb = exact_lcb_rank_value(right)
    left_bound = decimal_value(
        left.get("total_lcb_numeric_error_bound_usd_exact_decimal")
    )
    right_bound = decimal_value(
        right.get("total_lcb_numeric_error_bound_usd_exact_decimal")
    )
    if (
        left_bound is None
        or right_bound is None
        or left_bound < 0
        or right_bound < 0
    ):
        return False
    if left_lcb == right_lcb:
        # A nominal tie is not a proven tie when either score has unresolved
        # numerical error: the hidden exact order could differ.
        return left_bound == 0 and right_bound == 0
    # Decimal arithmetic obeys the process-global precision (normally 28
    # digits).  Subtracting two serialized 80-digit scores under that default
    # can round a real, tiny gap to zero and incorrectly mark it resolved.
    # decimal_sum chooses precision from the actual exponents and is exact.
    exact_gap = decimal_difference(left_lcb, right_lcb)
    combined_bound = decimal_sum((left_bound, right_bound))
    return (
        exact_gap is not None
        and combined_bound is not None
        and exact_gap.copy_abs() > combined_bound
    )


def select_unambiguous_lcb_candidate(
    rows: Iterable[Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, str]:
    """Select by exact conservative LCB; refuse a top rank inside its error bound."""
    candidates = list(rows)
    if not candidates:
        return None, "NO_ELIGIBLE_CANDIDATES"

    def statistics(row: Mapping[str, Any]) -> Mapping[str, Any]:
        value = row.get("statistics")
        return value if isinstance(value, Mapping) else {}

    ordered = sorted(
        candidates,
        key=lambda row: (
            exact_lcb_rank_value(statistics(row)),
            exact_net_rank_value(statistics(row)),
            int(statistics(row).get("sample_count") or 0),
        ),
        reverse=True,
    )
    if len(ordered) > 1 and not lcb_rank_is_numerically_resolved(
        statistics(ordered[0]), statistics(ordered[1])
    ):
        return None, "NUMERIC_LCB_RANK_UNRESOLVED"
    return ordered[0], "NUMERIC_LCB_RANK_RESOLVED"


def profit_factor_above_one(statistics: Mapping[str, Any]) -> bool:
    """Treat loss-free positive samples explicitly without emitting Infinity."""
    if statistics.get("profit_factor_status") == "NO_LOSSES":
        return True
    value = decimal_value(
        statistics.get("profit_factor_exact_decimal")
        if statistics.get("profit_factor_exact_decimal") is not None
        else statistics.get("profit_factor")
    )
    return value is not None and value > 1


def stable_hash(payload: Mapping[str, Any]) -> str:
    material = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def summarize_train_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    value_key: str,
    timestamp_key: str,
    trial_count: int,
    family_alpha: float = 0.05,
) -> dict[str, Any]:
    """Return robust metrics and a Bonferroni daily lower confidence bound."""

    clean: list[tuple[int, Decimal]] = []
    for row in rows:
        exact_value = row.get(f"{value_key}_exact_decimal")
        value = decimal_value(
            exact_value if exact_value is not None else row.get(value_key)
        )
        timestamp = decimal_value(row.get(timestamp_key))
        if (
            value is None
            or float_not_above(value) is None
            or timestamp is None
            or isinstance(row.get(timestamp_key), bool)
            or timestamp <= 0
            or timestamp != timestamp.to_integral_value()
        ):
            continue
        clean.append((int(timestamp), value))
    clean.sort()
    values = [value for _, value in clean]
    by_day: dict[int, list[Decimal]] = defaultdict(list)
    for timestamp_ms, value in clean:
        by_day[int(timestamp_ms) // 86_400_000].append(value)
    daily_exact = [decimal_sum(by_day[key]) for key in sorted(by_day)]
    daily_exact = [value for value in daily_exact if value is not None]
    daily_converted = [float_not_above(value) for value in daily_exact]
    daily_representable = all(value is not None for value in daily_converted)
    daily = [value for value in daily_converted if value is not None]
    total_exact = decimal_sum(values) if values else None
    has_positive = any(value > 0 for value in values)
    has_negative = any(value < 0 for value in values)
    positive_values = [value for value in values if value > 0]
    total_positive = (
        decimal_sum(positive_values) if values else None
    )
    largest_positive = max(positive_values, default=Decimal(0)) if values else None
    profit_factor_status = (
        "NO_VALID_OBSERVATIONS"
        if not values
        else "MEASURED"
        if has_negative
        else "NO_LOSSES"
        if has_positive
        else "NO_NONZERO_PNL"
    )
    trials = max(1, int(trial_count))
    adjusted_alpha = min(0.499999, max(1e-12, float(family_alpha) / trials))
    z_upper = _certified_normal_critical_value_upper_bound(adjusted_alpha)
    profit_factor_value = profit_factor_exact(values)
    daily_lcb = total_lcb = None
    daily_lcb_exact = total_lcb_exact = None
    daily_lcb_upper = total_lcb_upper = None
    lcb_rounding_error = None
    daily_lcb_numeric_error = None
    if len(daily_exact) >= 3 and daily_representable:
        count = len(daily_exact)
        total_lcb_exact, total_lcb_upper = _lcb_rounding_interval(
            daily_exact, z_upper
        )
        with localcontext() as context:
            context.prec = LCB_DECIMAL_PRECISION
            context.rounding = ROUND_CEILING
            lcb_rounding_error = total_lcb_upper - total_lcb_exact
            daily_lcb_numeric_error = lcb_rounding_error / Decimal(count)
        with localcontext() as context:
            context.prec = LCB_DECIMAL_PRECISION
            context.rounding = ROUND_FLOOR
            daily_lcb_exact = total_lcb_exact / Decimal(count)
        with localcontext() as context:
            context.prec = LCB_DECIMAL_PRECISION
            context.rounding = ROUND_CEILING
            daily_lcb_upper = total_lcb_upper / Decimal(count)
        daily_lcb = float_not_above(daily_lcb_exact)
        total_lcb = float_not_above(total_lcb_exact)
    return {
        "schema_version": SCHEMA_VERSION,
        "sample_count": len(clean),
        "distinct_days": len(daily_exact),
        "lcb_status": (
            "NO_VALID_OBSERVATIONS"
            if not clean
            else "NUMERIC_UNREPRESENTABLE"
            if not daily_representable
            else "INSUFFICIENT_DISTINCT_DAYS"
            if len(daily_exact) < 3
            else "MEASURED"
        ),
        "net_pnl_usd": (
            float_not_above(total_exact) if total_exact is not None else None
        ),
        "net_pnl_usd_exact_decimal": (
            format(total_exact, "f") if total_exact is not None else None
        ),
        "profit_factor": (
            float_not_above(profit_factor_value)
            if profit_factor_value is not None
            else None
        ),
        "profit_factor_exact_decimal": (
            format(profit_factor_value, "f")
            if profit_factor_value is not None
            else None
        ),
        "profit_factor_status": profit_factor_status,
        "hit_rate": (sum(value > 0.0 for value in values) / len(values)) if values else None,
        "top_positive_trade_share": (
            top_positive_share(values) if values else None
        ),
        "largest_positive_trade_pnl_usd_exact_decimal": (
            format(largest_positive, "f") if largest_positive is not None else None
        ),
        "total_positive_trade_pnl_usd_exact_decimal": (
            format(total_positive, "f") if total_positive is not None else None
        ),
        "daily_net_pnl_usd": daily if daily_representable else None,
        "daily_net_pnl_usd_exact_decimal": [
            format(value, "f") for value in daily_exact
        ],
        "bonferroni_trial_count": trials,
        "family_alpha": float(family_alpha),
        "adjusted_one_sided_alpha": adjusted_alpha,
        "critical_z": float_not_below(z_upper),
        "critical_z_upper_bound_exact_decimal": format(z_upper, "f"),
        "daily_mean_lcb_usd": daily_lcb,
        "total_lcb_usd": total_lcb,
        "daily_mean_lcb_usd_exact_decimal": (
            format(daily_lcb_exact, "f") if daily_lcb_exact is not None else None
        ),
        "total_lcb_usd_exact_decimal": (
            format(total_lcb_exact, "f") if total_lcb_exact is not None else None
        ),
        "daily_mean_lcb_upper_bound_usd_exact_decimal": (
            format(daily_lcb_upper, "f") if daily_lcb_upper is not None else None
        ),
        "total_lcb_upper_bound_usd_exact_decimal": (
            format(total_lcb_upper, "f") if total_lcb_upper is not None else None
        ),
        "total_lcb_arithmetic_error_bound_usd_exact_decimal": (
            format(lcb_rounding_error, "f")
            if lcb_rounding_error is not None
            else None
        ),
        "total_lcb_final_rounding_error_bound_usd_exact_decimal": (
            "0" if lcb_rounding_error is not None
            else None
        ),
        "total_lcb_quantile_safety_margin_usd_exact_decimal": (
            "0" if lcb_rounding_error is not None
            else None
        ),
        "total_lcb_quantile_error_bound_usd_exact_decimal": (
            "0" if lcb_rounding_error is not None
            else None
        ),
        "total_lcb_numeric_error_bound_usd_exact_decimal": (
            format(lcb_rounding_error, "f")
            if lcb_rounding_error is not None
            else None
        ),
        "daily_mean_lcb_numeric_error_bound_usd_exact_decimal": (
            format(daily_lcb_numeric_error, "f")
            if daily_lcb_numeric_error is not None
            else None
        ),
        "lcb_numeric_method": "EXACT_RATIONAL_VARIANCE_OUTWARD_DECIMAL_INTERVAL_MILLS_041_V1",
    }


def summarize_daily_values(
    daily_values: Iterable[object],
    *,
    trial_count: int,
    family_alpha: float = 0.05,
) -> dict[str, Any]:
    """Apply the shared conservative LCB calculation to already-aggregated days."""
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(daily_values):
        value = decimal_value(raw)
        display_value = float_not_above(value) if value is not None else None
        if value is None or display_value is None:
            return {
                "schema_version": SCHEMA_VERSION,
                "sample_count": len(rows),
                "distinct_days": len(rows),
                "lcb_status": "NUMERIC_UNREPRESENTABLE",
                "daily_net_pnl_usd": None,
                "daily_net_pnl_usd_exact_decimal": [
                    row["net_exact_decimal"] for row in rows
                ],
                "daily_mean_lcb_usd_exact_decimal": None,
                "daily_mean_lcb_numeric_error_bound_usd_exact_decimal": None,
            }
        rows.append(
            {
                "ts": index * UTC_DAY_MS + 1,
                "net": display_value,
                "net_exact_decimal": format(value, "f"),
            }
        )
    return summarize_train_rows(
        rows,
        value_key="net",
        timestamp_key="ts",
        trial_count=trial_count,
        family_alpha=family_alpha,
    )


def summarize_complete_utc_days(
    rows: Iterable[Mapping[str, Any]],
    *,
    value_key: str,
    timestamp_key: str,
    complete_day_starts_ms: Iterable[object] | None,
) -> dict[str, Any]:
    """Compute calendar-day PnL only over explicitly proven complete UTC days."""
    if complete_day_starts_ms is None:
        return {
            "status": "UNMEASURABLE",
            "reason": "COMPLETE_UTC_DAY_COVERAGE_MISSING",
            "calendar_day_count": 0,
            "calendar_day_net_pnl_usd": [],
            "calendar_day_mean_net_pnl_usd": None,
            "active_day_mean_net_pnl_usd": None,
            "zero_trade_days": 0,
        }

    covered_days: list[int] = []
    for raw_day in complete_day_starts_ms:
        day = decimal_value(raw_day)
        if (
            day is None
            or isinstance(raw_day, bool)
            or day != day.to_integral_value()
            or day < 0
            or int(day) % UTC_DAY_MS != 0
        ):
            return {
                "status": "UNMEASURABLE",
                "reason": "INVALID_COMPLETE_UTC_DAY_COVERAGE",
                "calendar_day_count": 0,
                "calendar_day_net_pnl_usd": [],
                "calendar_day_mean_net_pnl_usd": None,
                "active_day_mean_net_pnl_usd": None,
                "zero_trade_days": 0,
            }
        covered_days.append(int(day))
    if not covered_days or len(set(covered_days)) != len(covered_days):
        return {
            "status": "UNMEASURABLE",
            "reason": "INVALID_COMPLETE_UTC_DAY_COVERAGE",
            "calendar_day_count": 0,
            "calendar_day_net_pnl_usd": [],
            "calendar_day_mean_net_pnl_usd": None,
            "active_day_mean_net_pnl_usd": None,
            "zero_trade_days": 0,
        }

    ordered_days = sorted(covered_days)
    if any(
        current - previous != UTC_DAY_MS
        for previous, current in zip(ordered_days, ordered_days[1:], strict=False)
    ):
        return {
            "status": "UNMEASURABLE",
            "reason": "NONCONTIGUOUS_COMPLETE_UTC_DAY_COVERAGE",
            "calendar_day_count": len(ordered_days),
            "calendar_day_net_pnl_usd": [],
            "calendar_day_mean_net_pnl_usd": None,
            "active_day_mean_net_pnl_usd": None,
            "zero_trade_days": 0,
        }
    day_net_rows: dict[int, list[Decimal]] = {
        day: [] for day in ordered_days
    }
    day_trade_count = dict.fromkeys(ordered_days, 0)
    for row in rows:
        exact_value = row.get(f"{value_key}_exact_decimal")
        value = decimal_value(
            exact_value if exact_value is not None else row.get(value_key)
        )
        timestamp = decimal_value(row.get(timestamp_key))
        if (
            value is None
            or timestamp is None
            or isinstance(row.get(timestamp_key), bool)
            or timestamp < 0
            or timestamp != timestamp.to_integral_value()
        ):
            return {
                "status": "UNMEASURABLE",
                "reason": "INVALID_TRADE_ROW_FOR_CALENDAR_PNL",
                "calendar_day_count": len(ordered_days),
                "calendar_day_net_pnl_usd": [],
                "calendar_day_mean_net_pnl_usd": None,
                "active_day_mean_net_pnl_usd": None,
                "zero_trade_days": 0,
            }
        day_start = int(timestamp) // UTC_DAY_MS * UTC_DAY_MS
        if day_start not in day_net_rows:
            return {
                "status": "UNMEASURABLE",
                "reason": "TRADE_OUTSIDE_COMPLETE_UTC_DAY_COVERAGE",
                "calendar_day_count": len(ordered_days),
                "calendar_day_net_pnl_usd": [],
                "calendar_day_mean_net_pnl_usd": None,
                "active_day_mean_net_pnl_usd": None,
                "zero_trade_days": 0,
            }
        day_net_rows[day_start].append(value)
        day_trade_count[day_start] += 1

    exact_values = [decimal_sum(day_net_rows[day]) for day in ordered_days]
    if any(value is None for value in exact_values):
        return {
            "status": "UNMEASURABLE",
            "reason": "PNL_AGGREGATE_UNREPRESENTABLE",
            "calendar_day_count": len(ordered_days),
            "calendar_day_net_pnl_usd": [],
            "calendar_day_mean_net_pnl_usd": None,
            "active_day_mean_net_pnl_usd": None,
            "zero_trade_days": 0,
        }
    daily_exact_values = [value for value in exact_values if value is not None]
    active = [
        daily_exact_values[index]
        for index, day in enumerate(ordered_days)
        if day_trade_count[day] > 0
    ]
    calendar_total = decimal_sum(daily_exact_values)
    if calendar_total is None:
        return {
            "status": "UNMEASURABLE",
            "reason": "PNL_AGGREGATE_UNREPRESENTABLE",
            "calendar_day_count": len(ordered_days),
            "calendar_day_net_pnl_usd": [],
            "calendar_day_mean_net_pnl_usd": None,
            "active_day_mean_net_pnl_usd": None,
            "zero_trade_days": 0,
        }
    with localcontext() as context:
        context.prec = LCB_DECIMAL_PRECISION
        context.rounding = ROUND_FLOOR
        calendar_mean = calendar_total / Decimal(len(daily_exact_values))
        active_mean = (
            decimal_sum(active) / Decimal(len(active)) if active else None
        )
    calendar_floats = [float_not_above(value) for value in daily_exact_values]
    if (
        any(value is None for value in calendar_floats)
        or float_not_above(calendar_total) is None
        or float_not_above(calendar_mean) is None
        or (active_mean is not None and float_not_above(active_mean) is None)
    ):
        return {
            "status": "UNMEASURABLE",
            "reason": "PNL_AGGREGATE_UNREPRESENTABLE",
            "calendar_day_count": len(ordered_days),
            "calendar_day_net_pnl_usd": [],
            "calendar_day_mean_net_pnl_usd": None,
            "active_day_mean_net_pnl_usd": None,
            "zero_trade_days": 0,
        }
    return {
        "status": "MEASURABLE",
        "reason": None,
        "calendar_day_count": len(ordered_days),
        "active_day_count": len(active),
        "zero_trade_days": sum(count == 0 for count in day_trade_count.values()),
        "calendar_day_starts_ms": ordered_days,
        "calendar_day_net_pnl_usd": calendar_floats,
        "calendar_day_net_pnl_usd_exact_decimal": [
            format(value, "f") for value in daily_exact_values
        ],
        "calendar_day_mean_net_pnl_usd": float_not_above(calendar_mean),
        "calendar_day_mean_net_pnl_usd_exact_decimal": format(calendar_mean, "f"),
        "active_day_mean_net_pnl_usd": (
            float_not_above(active_mean) if active_mean is not None else None
        ),
        "active_day_mean_net_pnl_usd_exact_decimal": (
            format(active_mean, "f") if active_mean is not None else None
        ),
        "calendar_total_net_pnl_usd": float_not_above(calendar_total),
        "calendar_total_net_pnl_usd_exact_decimal": format(calendar_total, "f"),
    }


__all__ = [
    "SCHEMA_VERSION",
    "number",
    "profit_factor",
    "profit_factor_exact",
    "profit_factor_above_one",
    "exact_net_rank_value",
    "exact_lcb_rank_value",
    "lcb_rank_is_numerically_resolved",
    "select_unambiguous_lcb_candidate",
    "stable_hash",
    "summarize_train_rows",
    "summarize_daily_values",
    "summarize_complete_utc_days",
    "top_positive_share",
    "top_positive_share_within_limit",
    "UTC_DAY_MS",
]
