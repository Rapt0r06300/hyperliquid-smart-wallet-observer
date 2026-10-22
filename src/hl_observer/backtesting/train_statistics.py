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
from statistics import NormalDist, fmean, stdev
from typing import Any

SCHEMA_VERSION = "hypersmart.train_selection_statistics.v1"
UTC_DAY_MS = 86_400_000


def number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def profit_factor(values: Iterable[float]) -> float | None:
    rows = [float(value) for value in values if math.isfinite(float(value))]
    wins = sum(value for value in rows if value > 0.0)
    losses = -sum(value for value in rows if value < 0.0)
    if losses <= 1e-12:
        return float("inf") if wins > 1e-12 else None
    return wins / losses


def top_positive_share(values: Iterable[float]) -> float:
    positives = [float(value) for value in values if math.isfinite(float(value)) and value > 0.0]
    total = sum(positives)
    return max(positives, default=0.0) / total if total > 1e-12 else 1.0


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

    clean: list[tuple[int, float]] = []
    for row in rows:
        value = number(row.get(value_key))
        timestamp = number(row.get(timestamp_key))
        if value is None or timestamp is None or timestamp <= 0:
            continue
        clean.append((int(timestamp), float(value)))
    clean.sort()
    values = [value for _, value in clean]
    by_day: dict[int, float] = defaultdict(float)
    for timestamp_ms, value in clean:
        by_day[int(timestamp_ms) // 86_400_000] += value
    daily = [by_day[key] for key in sorted(by_day)]
    trials = max(1, int(trial_count))
    adjusted_alpha = min(0.499999, max(1e-12, float(family_alpha) / trials))
    z = NormalDist().inv_cdf(1.0 - adjusted_alpha)
    daily_lcb = total_lcb = None
    if len(daily) >= 3:
        mean = fmean(daily)
        sigma = stdev(daily) if len(daily) > 1 else 0.0
        standard_error = sigma / math.sqrt(len(daily))
        daily_lcb = mean - z * standard_error
        total_lcb = daily_lcb * len(daily)
    return {
        "schema_version": SCHEMA_VERSION,
        "sample_count": len(clean),
        "distinct_days": len(daily),
        "net_pnl_usd": round(sum(values), 10),
        "profit_factor": profit_factor(values),
        "hit_rate": (sum(value > 0.0 for value in values) / len(values)) if values else None,
        "top_positive_trade_share": top_positive_share(values),
        "daily_net_pnl_usd": [round(value, 10) for value in daily],
        "bonferroni_trial_count": trials,
        "family_alpha": float(family_alpha),
        "adjusted_one_sided_alpha": adjusted_alpha,
        "critical_z": z,
        "daily_mean_lcb_usd": daily_lcb,
        "total_lcb_usd": total_lcb,
    }


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
        day = number(raw_day)
        if (
            day is None
            or isinstance(raw_day, bool)
            or not day.is_integer()
            or int(day) < 0
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
    day_net = dict.fromkeys(ordered_days, 0.0)
    for row in rows:
        value = number(row.get(value_key))
        timestamp = number(row.get(timestamp_key))
        if value is None or timestamp is None or timestamp < 0:
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
        if day_start not in day_net:
            return {
                "status": "UNMEASURABLE",
                "reason": "TRADE_OUTSIDE_COMPLETE_UTC_DAY_COVERAGE",
                "calendar_day_count": len(ordered_days),
                "calendar_day_net_pnl_usd": [],
                "calendar_day_mean_net_pnl_usd": None,
                "active_day_mean_net_pnl_usd": None,
                "zero_trade_days": 0,
            }
        day_net[day_start] += value

    values = [day_net[day] for day in ordered_days]
    active = [value for value in values if value != 0.0]
    return {
        "status": "MEASURABLE",
        "reason": None,
        "calendar_day_count": len(ordered_days),
        "active_day_count": sum(day != 0.0 for day in values),
        "zero_trade_days": sum(day == 0.0 for day in values),
        "calendar_day_starts_ms": ordered_days,
        "calendar_day_net_pnl_usd": [round(value, 10) for value in values],
        "calendar_day_mean_net_pnl_usd": fmean(values),
        "active_day_mean_net_pnl_usd": fmean(active) if active else None,
        "calendar_total_net_pnl_usd": round(sum(values), 10),
    }


__all__ = [
    "SCHEMA_VERSION",
    "number",
    "profit_factor",
    "stable_hash",
    "summarize_train_rows",
    "summarize_complete_utc_days",
    "top_positive_share",
    "UTC_DAY_MS",
]
