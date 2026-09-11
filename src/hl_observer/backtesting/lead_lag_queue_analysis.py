"""Pure shock preparation and reporting helpers for queue-aware Lead-Lag replay."""
from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from typing import Any


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def detect_rolling_shocks(
    trades: Sequence[Sequence[float]],
    *,
    window_ms: int,
    threshold_bps: float,
    cooldown_ms: int,
) -> list[dict[str, Any]]:
    """Detect causal rolling-price shocks without consulting future trades."""

    clean: list[tuple[int, float]] = []
    for row in trades:
        if len(row) < 2:
            continue
        timestamp_ns = _number(row[0])
        price = _number(row[1])
        if timestamp_ns is None or price is None or timestamp_ns <= 0 or price <= 0:
            continue
        clean.append((int(timestamp_ns), float(price)))
    clean.sort()

    result: list[dict[str, Any]] = []
    left = 0
    last_trigger_ms = -10**18
    window_ns = max(1, int(window_ms)) * 1_000_000
    for index, (timestamp_ns, price) in enumerate(clean):
        while left < index and timestamp_ns - clean[left][0] > window_ns:
            left += 1
        if left >= index:
            continue
        base_timestamp_ns, base_price = clean[left]
        shock_bps = (price - base_price) / base_price * 10_000.0
        trigger_ms = timestamp_ns // 1_000_000
        if abs(shock_bps) < float(threshold_bps):
            continue
        if trigger_ms - last_trigger_ms < max(0, int(cooldown_ms)):
            continue
        result.append(
            {
                "trigger_ts_ms": int(trigger_ms),
                "window_start_ts_ms": int(base_timestamp_ns // 1_000_000),
                "lead_start_price": float(base_price),
                "lead_trigger_price": float(price),
                "lead_shock_bps": float(shock_bps),
                "direction": 1 if shock_bps > 0 else -1,
            }
        )
        last_trigger_ms = trigger_ms
    return result


def assign_shock_segments(
    shocks: list[dict[str, Any]],
    segment_bounds: Mapping[str, tuple[int | None, int | None]] | None = None,
) -> None:
    """Freeze chronological segments before knowing which orders fill."""

    shocks.sort(key=lambda row: int(row["trigger_ts_ms"]))
    if segment_bounds is not None:
        for row in shocks:
            timestamp = int(row["trigger_ts_ms"])
            matches = [
                str(segment)
                for segment, bounds in segment_bounds.items()
                if bounds is not None
                and len(bounds) == 2
                and bounds[0] is not None
                and bounds[1] is not None
                and int(bounds[0]) <= timestamp <= int(bounds[1])
            ]
            if len(matches) > 1:
                raise ValueError("OVERLAPPING_EXPLICIT_SEGMENT_BOUNDS")
            row["walk_forward_segment"] = matches[0] if matches else "excluded"
        return

    count = len(shocks)
    train_end = int(count * 0.60)
    validation_end = int(count * 0.80)
    for index, row in enumerate(shocks):
        if index < train_end:
            segment = "train"
        elif index < validation_end:
            segment = "validation"
        else:
            segment = "oos"
        row["walk_forward_segment"] = segment


def summarize_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Summarize closed paper rows without changing replay state."""

    nets = [float(row.get("net_pnl_usd") or 0.0) for row in rows]
    wins = sum(value for value in nets if value > 0)
    losses = -sum(value for value in nets if value < 0)
    trade_ids = [str(row.get("trade_id") or "") for row in rows]
    duplicate_ids = len(trade_ids) - len(set(trade_ids))
    cumulative = peak = max_drawdown = 0.0
    for value in nets:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = min(max_drawdown, cumulative - peak)
    total_notional = sum(float(row.get("notional_usd") or 0.0) for row in rows)
    liquidatable_count = sum(row.get("LIQUIDATABLE_NET") is True for row in rows)
    closed_positions = sum(row.get("closed_position") is True for row in rows)
    return {
        "sample_count": len(rows),
        "positions_ouvertes": len(rows),
        "positions_fermees": closed_positions,
        "gross_pnl_usd": round(sum(float(row.get("gross_pnl_usd") or 0.0) for row in rows), 8),
        "fees_usd": round(sum(float(row.get("fees_usd") or 0.0) for row in rows), 8),
        "spread_cost_usd": round(sum(float(row.get("spread_cost_usd") or 0.0) for row in rows), 8),
        "slippage_cost_usd": round(sum(float(row.get("slippage_cost_usd") or 0.0) for row in rows), 8),
        "latency_cost_usd": round(sum(float(row.get("latency_cost_usd") or 0.0) for row in rows), 8),
        "net_pnl_usd": round(sum(nets), 8),
        "roi_pct": round(sum(nets) / total_notional * 100.0, 8) if total_notional > 0 else None,
        "max_drawdown_usd": round(abs(max_drawdown), 8),
        "hit_rate": sum(value > 0 for value in nets) / len(nets) if nets else None,
        "profit_factor": (
            float("inf") if wins > 0 and losses <= 1e-12 else (wins / losses if losses > 0 else None)
        ),
        "liquidatable_count": liquidatable_count,
        "closed_positions": closed_positions,
        "LIQUIDATABLE_NET": bool(rows)
        and liquidatable_count == len(rows)
        and closed_positions == len(rows),
        "trade_ids_count": len(set(trade_ids)),
        "duplicate_trade_ids": duplicate_ids,
        "trade_ids_sha256": hashlib.sha256("\n".join(sorted(trade_ids)).encode("utf-8")).hexdigest(),
    }


def validate_precomputed_shocks(
    rows: Sequence[Mapping[str, Any]],
    *,
    window_ms: int,
    threshold_bps: float,
    cooldown_ms: int,
) -> list[dict[str, Any]]:
    """Validate a causal streaming index before using it in the queue replay."""

    shocks: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for raw in rows:
        trigger = _number(raw.get("trigger_ts_ms"))
        window_start = _number(raw.get("window_start_ts_ms"))
        start_price = _number(raw.get("lead_start_price"))
        trigger_price = _number(raw.get("lead_trigger_price"))
        recorded_bps = _number(raw.get("lead_shock_bps"))
        if (
            trigger is None
            or window_start is None
            or start_price is None
            or trigger_price is None
            or recorded_bps is None
            or trigger <= 0
            or window_start <= 0
            or start_price <= 0
            or trigger_price <= 0
            or window_start > trigger
            or trigger - window_start > max(1, int(window_ms))
        ):
            raise ValueError("INVALID_PRECOMPUTED_SHOCK")
        recomputed_bps = (trigger_price - start_price) / start_price * 10_000.0
        direction = 1 if recomputed_bps > 0 else -1
        if (
            not math.isclose(recomputed_bps, recorded_bps, rel_tol=1e-10, abs_tol=1e-10)
            or int(raw.get("direction") or 0) != direction
            or abs(recomputed_bps) < float(threshold_bps)
        ):
            raise ValueError("INCONSISTENT_PRECOMPUTED_SHOCK")
        identity = (int(trigger), int(window_start), float(start_price), float(trigger_price))
        if identity in seen:
            raise ValueError("DUPLICATE_PRECOMPUTED_SHOCK")
        seen.add(identity)
        shocks.append(
            {
                "trigger_ts_ms": int(trigger),
                "window_start_ts_ms": int(window_start),
                "lead_start_price": float(start_price),
                "lead_trigger_price": float(trigger_price),
                "lead_shock_bps": float(recorded_bps),
                "direction": direction,
            }
        )
    shocks.sort(key=lambda row: int(row["trigger_ts_ms"]))
    previous = -10**18
    for row in shocks:
        trigger = int(row["trigger_ts_ms"])
        if trigger - previous < max(0, int(cooldown_ms)):
            raise ValueError("PRECOMPUTED_SHOCK_COOLDOWN_VIOLATION")
        previous = trigger
    return shocks


__all__ = [
    "_number",
    "assign_shock_segments",
    "detect_rolling_shocks",
    "summarize_rows",
    "validate_precomputed_shocks",
]
