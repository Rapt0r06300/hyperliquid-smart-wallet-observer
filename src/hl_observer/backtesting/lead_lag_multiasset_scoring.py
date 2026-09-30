"""Outcome aggregation and train-only scoring for multi-asset Lead-Lag research."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any


def shock_timestamps(
    tape: Mapping[str, Mapping[str, list]],
    *,
    minimum_threshold: float,
    detector: Callable[..., list[tuple[int, int]]],
) -> list[int]:
    timestamps: set[int] = set()
    for streams in tape.values():
        trades = list(streams.get("TRADE") or [])
        for timestamp_ns, _direction in detector(trades, seuil_bps=minimum_threshold):
            timestamps.add(int(timestamp_ns // 1_000_000))
    return sorted(timestamps)


def rows_from_ledgers(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    ledgers = report.get("ledgers")
    if not isinstance(ledgers, Mapping):
        return result
    for label in ("IS", "OOS", "FORWARD"):
        rows = ledgers.get(label)
        if not isinstance(rows, list):
            continue
        signals: dict[str, tuple[int, str]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            trade_id = str(row.get("trade_id") or "")
            if not trade_id:
                continue
            if row.get("evt") == "SIGNAL":
                signals[trade_id] = (int(row.get("ts") or 0), str(row.get("coin") or ""))
            elif row.get("evt") == "PNL" and row.get("LIQUIDATABLE_NET") is True:
                try:
                    net = float(row.get("pnl_usd"))
                except (TypeError, ValueError, OverflowError):
                    continue
                timestamp, coin = signals.get(trade_id, (0, ""))
                if timestamp > 0:
                    result.append(
                        {
                            "trade_id": trade_id,
                            "timestamp_ms": timestamp,
                            "coin": coin,
                            "net_pnl_usd": net,
                            "internal_train_fold": label,
                        }
                    )
    return result


def independent_train_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    horizon_ms: int,
    shock_window_ms: float | None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Keep a deterministic, outcome-blind set of non-overlapping episodes."""
    minimum_separation_ms = max(
        1,
        int(horizon_ms),
        int(math.ceil(float(shock_window_ms))) if shock_window_ms is not None else 0,
    )
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            int(row.get("timestamp_ms") or 0),
            str(row.get("coin") or ""),
            str(row.get("trade_id") or ""),
        ),
    )
    accepted: list[dict[str, Any]] = []
    last_timestamp_by_coin: dict[str, int] = {}
    rejected = 0
    for row in ordered:
        timestamp_ms = int(row.get("timestamp_ms") or 0)
        coin = str(row.get("coin") or "").upper()
        if timestamp_ms <= 0 or not coin:
            rejected += 1
            continue
        previous = last_timestamp_by_coin.get(coin)
        if previous is not None and timestamp_ms - previous < minimum_separation_ms:
            rejected += 1
            continue
        accepted.append(row)
        last_timestamp_by_coin[coin] = timestamp_ms
    effective_days = len({int(row["timestamp_ms"]) // 86_400_000 for row in accepted})
    return accepted, {
        "raw_sample_count": len(rows),
        "effective_sample_count": len(accepted),
        "overlapping_events_rejected": rejected,
        "minimum_separation_ms": minimum_separation_ms,
        "effective_distinct_days": effective_days,
    }


def score_report(
    report: Mapping[str, Any],
    *,
    coin: str,
    threshold_bps: float,
    horizon_ms: int,
    trial_count: int,
    mechanism: str,
    direction_multiplier: int,
    min_train_fills: int,
    shock_window_ms: float | None,
    admission_policy: str,
    economic_predeclaration_id: str | None,
    family_alpha: float,
    diagnostic_only_threshold_bps: float,
    min_distinct_days: int,
    max_top_positive_share: float,
    rows_loader: Callable[[Mapping[str, Any]], list[dict[str, Any]]],
    independence_filter: Callable[..., tuple[list[dict[str, Any]], dict[str, int]]],
    summarizer: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    raw_rows = rows_loader(report)
    rows, independence = independence_filter(
        raw_rows, horizon_ms=horizon_ms, shock_window_ms=shock_window_ms
    )
    stats = summarizer(
        rows,
        value_key="net_pnl_usd",
        timestamp_key="timestamp_ms",
        trial_count=trial_count,
        family_alpha=family_alpha,
    )
    segments = report.get("segments") if isinstance(report.get("segments"), Mapping) else {}
    internal_fold_nets = {
        label: float((segments.get(label) or {}).get("net") or 0.0)
        for label in ("IS", "OOS", "FORWARD")
    }
    placebo_net = float(report.get("placebo_net") or 0.0)
    net = float(stats.get("net_pnl_usd") or 0.0)
    pf = stats.get("profit_factor")
    lcb = stats.get("total_lcb_usd")
    economic_predeclaration = str(economic_predeclaration_id or "").strip() or None
    economic_threshold_allowed = (
        float(threshold_bps) != diagnostic_only_threshold_bps
        or economic_predeclaration is not None
    )
    eligible = bool(
        economic_threshold_allowed
        and report.get("costs_measured") is True
        and int(independence["effective_sample_count"]) >= int(min_train_fills)
        and int(independence["effective_distinct_days"]) >= min_distinct_days
        and int(stats.get("sample_count") or 0) >= int(min_train_fills)
        and int(stats.get("distinct_days") or 0) >= min_distinct_days
        and net > 0.0
        and pf is not None
        and float(pf) > 1.0
        and lcb is not None
        and float(lcb) > 0.0
        and float(stats.get("top_positive_trade_share") or 1.0) <= max_top_positive_share
        and net > placebo_net + 1e-12
        and all(value > 0.0 for value in internal_fold_nets.values())
    )
    return {
        "mechanism": str(mechanism),
        "direction_multiplier": int(direction_multiplier),
        "direction_policy": (
            "CUMULATIVE_WINDOW_CONTINUATION"
            if shock_window_ms is not None and int(direction_multiplier) == 1
            else ("SHOCK_CONTINUATION" if int(direction_multiplier) == 1 else "EXTREME_SHOCK_REVERSAL")
        ),
        "coin": str(coin).upper(),
        "shock_threshold_bps": float(threshold_bps),
        "threshold_role": "TRAIN_ECONOMIC_PREDECLARED" if economic_threshold_allowed else "DIAGNOSTIC_ONLY",
        "economic_threshold_allowed": economic_threshold_allowed,
        "economic_predeclaration_id": economic_predeclaration,
        "horizon_ms": int(horizon_ms),
        "shock_window_ms": float(shock_window_ms) if shock_window_ms is not None else None,
        "admission_policy": str(admission_policy),
        "statistics": stats,
        "independence": independence,
        "internal_train_fold_nets": internal_fold_nets,
        "placebo_net_pnl_usd": placebo_net,
        "minimum_train_fills": int(min_train_fills),
        "coverage": dict(report.get("coverage") or {}),
        "signals": int(report.get("signals") or 0),
        "decision_counts": dict(report.get("decision_counts") or {}),
        "raw_observation_diagnostics": dict(report.get("raw_observation_diagnostics") or {}),
        "raw_direction_flip_diagnostics": dict(report.get("raw_direction_flip_diagnostics") or {}),
        "eligible": eligible,
    }


__all__ = ["independent_train_rows", "rows_from_ledgers", "score_report", "shock_timestamps"]
