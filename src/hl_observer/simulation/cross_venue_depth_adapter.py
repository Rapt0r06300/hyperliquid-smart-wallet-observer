"""Causal L2/top-of-book capacity proof for Cross-Venue paper replays.

``carnet_venues.jsonl`` records both venues' executable top quotes and the
minimum USD capacity across the four top-of-book sides.  A replay trade may
claim zero *additional* depth slippage only when an observation exists at or
before entry AND exit, is fresh, and covers the paper notional.  Future, stale
or undersized depth never becomes a zero-cost assumption.
"""
from __future__ import annotations

import bisect
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

DEFAULT_DEPTH_FRESHNESS_MS = 3_000.0
DEPTH_PATH = Path("runtime") / "data" / "carnet_venues.jsonl"


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _timestamp_ms(row: Mapping[str, Any]) -> int | None:
    for key in ("ts_ms", "ts_wall_ms", "recv_wall_ts_ms", "received_ts_ms"):
        value = _number(row.get(key))
        if value is not None and value >= 1_500_000_000_000:
            return int(value)
    collected = _number(row.get("collecte_ts"))
    if collected is not None and collected >= 1_500_000_000:
        return int(collected * 1000.0)
    return None


def load_depth_snapshots(root: str | Path) -> dict[str, list[dict[str, Any]]]:
    path = Path(root) / DEPTH_PATH
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not path.is_file():
        return {}
    try:
        handle = path.open("r", encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    with handle:
        for line in handle:
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if not isinstance(row, dict):
                continue
            coin = str(row.get("coin") or "").upper().strip()
            ts_ms = _timestamp_ms(row)
            capacity = _number(row.get("taille_min_usd"))
            if not coin or ts_ms is None or capacity is None or capacity < 0:
                continue
            grouped[coin].append({**row, "_ts_ms": ts_ms, "_capacity_usd": capacity})
    for rows in grouped.values():
        rows.sort(key=lambda row: int(row["_ts_ms"]))
    return dict(grouped)


def _at_or_before(
    rows: list[dict[str, Any]],
    ts_ms: float,
    *,
    freshness_ms: float,
) -> tuple[dict[str, Any] | None, float | None]:
    if not rows:
        return None, None
    times = [int(row["_ts_ms"]) for row in rows]
    index = bisect.bisect_right(times, int(ts_ms)) - 1
    if index < 0:
        return None, None
    row = rows[index]
    age = float(ts_ms) - float(row["_ts_ms"])
    if age < 0 or age > float(freshness_ms):
        return None, age
    return row, age


def enrich_trades_with_depth(
    trades: Iterable[Mapping[str, Any]],
    snapshots: Mapping[str, list[dict[str, Any]]],
    *,
    notional_usd: float,
    freshness_ms: float = DEFAULT_DEPTH_FRESHNESS_MS,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    notional = float(notional_usd)
    for original in trades:
        trade = dict(original)
        coin = str(trade.get("coin") or "").upper()
        entry_ts = _number(trade.get("ts_in"))
        exit_ts = _number(trade.get("ts_out"))
        rows = list(snapshots.get(coin) or [])
        reason = None
        entry_row = exit_row = None
        entry_age = exit_age = None
        if entry_ts is None or exit_ts is None:
            reason = "TRADE_TIMESTAMP_MISSING"
        elif not rows:
            reason = "DEPTH_MISSING"
        else:
            entry_row, entry_age = _at_or_before(rows, entry_ts, freshness_ms=freshness_ms)
            exit_row, exit_age = _at_or_before(rows, exit_ts, freshness_ms=freshness_ms)
            if entry_row is None:
                reason = "ENTRY_DEPTH_STALE_OR_FUTURE_ONLY"
            elif exit_row is None:
                reason = "EXIT_DEPTH_STALE_OR_FUTURE_ONLY"
            elif float(entry_row["_capacity_usd"]) < notional:
                reason = "ENTRY_TOP_CAPACITY_INSUFFICIENT"
            elif float(exit_row["_capacity_usd"]) < notional:
                reason = "EXIT_TOP_CAPACITY_INSUFFICIENT"

        if reason is None and entry_row is not None and exit_row is not None:
            # BBO already prices the top quote. If all four top sides cover the
            # paper notional at entry and exit, no extra depth level is crossed.
            trade["slippage_bps"] = 0.0
            trade["slippage_cost_usd"] = 0.0
            trade["slippage_proof"] = "MEASURED_TOP_LEVEL_CAPACITY"
            trade["entry_depth_age_ms"] = round(float(entry_age or 0.0), 3)
            trade["exit_depth_age_ms"] = round(float(exit_age or 0.0), 3)
            trade["entry_capacity_usd"] = round(float(entry_row["_capacity_usd"]), 6)
            trade["exit_capacity_usd"] = round(float(exit_row["_capacity_usd"]), 6)
            gross = _number(trade.get("gross_signal_bps"))
            fees = _number(trade.get("fees_bps"))
            spread = _number(trade.get("spread_cost_bps"))
            latency = _number(trade.get("latency_cost_bps"))
            net = _number(trade.get("net_bps"))
            reconciled = all(value is not None for value in (gross, fees, spread, latency, net))
            if reconciled:
                expected = float(gross) - float(fees) - float(spread) - float(latency)
                reconciled = math.isclose(expected, float(net), abs_tol=1e-3)
            trade["economic_reconciled"] = bool(reconciled)
            trade["LIQUIDATABLE_NET"] = bool(reconciled and trade.get("two_leg") is True)
            trade["depth_reason"] = "MEASURED"
        else:
            trade["slippage_bps"] = None
            trade["slippage_cost_usd"] = None
            trade["slippage_proof"] = None
            trade["LIQUIDATABLE_NET"] = False
            trade["depth_reason"] = reason
            trade["entry_depth_age_ms"] = entry_age
            trade["exit_depth_age_ms"] = exit_age
        enriched.append(trade)
    return enriched


def finalize_judgement(
    trades: list[Mapping[str, Any]],
    base: Mapping[str, Any],
    *,
    notional_usd: float,
) -> dict[str, Any]:
    """Attach measured slippage totals without weakening the base robustness verdict."""
    result = dict(base)
    measured = bool(trades) and all(_number(trade.get("slippage_bps")) is not None for trade in trades)
    if measured:
        slippage_usd = sum(
            float(trade.get("slippage_bps") or 0.0) / 1e4 * float(notional_usd)
            for trade in trades
        )
        result["slippage_cost_usd"] = round(slippage_usd, 6)
    else:
        result["slippage_cost_usd"] = None
    result["LIQUIDATABLE_NET"] = bool(
        trades
        and measured
        and all(trade.get("LIQUIDATABLE_NET") is True for trade in trades)
        and result.get("positions_ouvertes") == result.get("positions_fermees") == len(trades)
    )
    result["depth_measured_trades"] = sum(
        1 for trade in trades if trade.get("slippage_proof") == "MEASURED_TOP_LEVEL_CAPACITY"
    )
    reasons: dict[str, int] = {}
    for trade in trades:
        reason = str(trade.get("depth_reason") or "UNKNOWN")
        reasons[reason] = reasons.get(reason, 0) + 1
    result["depth_reason_counts"] = reasons
    return result


__all__ = [
    "DEFAULT_DEPTH_FRESHNESS_MS",
    "enrich_trades_with_depth",
    "finalize_judgement",
    "load_depth_snapshots",
]
