"""Measured causal execution primitives for Lead-Lag paper replay."""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.economics.assumptions import CostComponentReceipt, ZeroCostReason
from hl_observer.economics.families import build_lead_lag_contract

DEFAULT_DECISIONS = Path("runtime") / "data" / "lead_lag_event_decisions.jsonl"
DEFAULT_MIN_LATENCY_SAMPLES = 20
DEFAULT_MAX_BOOK_AGE_MS = 750.0
DEFAULT_MAX_EXECUTION_OBSERVATION_DELAY_MS = 750.0
DEFAULT_FEE_BPS = float(
    build_lead_lag_contract()
    .registry.get("lead_lag.round_trip_fee_bps")
    .value
)
LATENCY_KIND_LOCAL_MONOTONIC = "LOCAL_MONOTONIC_DISPATCH"
ADMISSION_PRIOR_MEAN_POSITIVE = "PRIOR_MEAN_POSITIVE"
ADMISSION_PREDECLARED_ALL_SIGNALS = "PREDECLARED_ALL_CAUSAL_SIGNALS"


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _percentile_nearest_rank(values: list[float], percentile: float) -> float | None:
    clean = sorted(value for value in values if math.isfinite(value) and value >= 0)
    if not clean:
        return None
    rank = max(1, math.ceil(float(percentile) * len(clean)))
    return clean[min(len(clean), rank) - 1]


def load_runtime_latency_evidence(
    root: str | Path,
    *,
    min_samples: int = DEFAULT_MIN_LATENCY_SAMPLES,
    max_lines: int = 100_000,
) -> dict[str, Any]:
    """Read measured event-loop latency; never invent a zero-latency default."""
    path = Path(root) / DEFAULT_DECISIONS
    values: list[float] = []
    total = 0
    invalid = 0
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        lines = []
    if max_lines > 0:
        lines = lines[-max_lines:]
    for line in lines:
        try:
            row = json.loads(line)
        except (TypeError, ValueError):
            invalid += 1
            continue
        if not isinstance(row, Mapping):
            invalid += 1
            continue
        total += 1
        if (
            row.get("sample_only") is not True
            or row.get("latency_kind") != LATENCY_KIND_LOCAL_MONOTONIC
        ):
            continue
        latency = _number(row.get("latency_ms"))
        if latency is None or latency < 0:
            continue
        values.append(float(latency))
    p95 = _percentile_nearest_rank(values, 0.95)
    measured = len(values) >= max(1, int(min_samples)) and p95 is not None
    return {
        "schema_version": "hypersmart.lead_lag_runtime_latency.v2",
        "path": DEFAULT_DECISIONS.as_posix(),
        "rows_seen": total,
        "samples": len(values),
        "invalid_rows": invalid,
        "min_samples": int(min_samples),
        "p50_ms": round(float(statistics.median(values)), 6) if values else None,
        "p95_ms": round(float(p95), 6) if p95 is not None else None,
        "max_ms": round(max(values), 6) if values else None,
        "measured": measured,
        "read_only": True,
        "real_execution": False,
    }


def _latest_at_or_before(
    rows: list[Mapping[str, Any]],
    target_ms: float,
    *,
    max_age_ms: float,
    times: Sequence[int] | None = None,
) -> Mapping[str, Any] | None:
    if not rows:
        return None
    ordered_times = (
        times if times is not None else [int(row.get("ts_ms") or 0) for row in rows]
    )
    index = bisect.bisect_right(ordered_times, int(target_ms)) - 1
    if index < 0:
        return None
    row = rows[index]
    age = float(target_ms) - float(row.get("ts_ms") or 0)
    if age < 0 or age > float(max_age_ms):
        return None
    return row


def _first_at_or_after(
    rows: list[Mapping[str, Any]],
    target_ms: float,
    *,
    max_delay_ms: float,
    times: Sequence[int] | None = None,
) -> Mapping[str, Any] | None:
    if not rows:
        return None
    ordered_times = (
        times if times is not None else [int(row.get("ts_ms") or 0) for row in rows]
    )
    index = bisect.bisect_left(ordered_times, int(math.ceil(target_ms)))
    if index >= len(rows):
        return None
    row = rows[index]
    delay = float(row.get("ts_ms") or 0) - float(target_ms)
    if delay < 0 or delay > float(max_delay_ms):
        return None
    return row


def _book_for_execution(
    rows: list[Mapping[str, Any]],
    target_ms: float,
    *,
    max_age_ms: float,
    max_delay_ms: float,
    times: Sequence[int] | None = None,
) -> tuple[Mapping[str, Any], float, str] | None:
    """Select a causal executable book without pretending a stale mark is current.

    The latest already-observed book is executable at ``target_ms`` while it is
    still fresh.  Otherwise the replay waits for the first bounded subsequent
    observation and moves the execution timestamp to that observation.  The
    latter is delayed execution, not look-ahead at the original target.
    """

    latest = _latest_at_or_before(
        rows,
        target_ms,
        max_age_ms=max_age_ms,
        times=times,
    )
    if latest is not None:
        return latest, float(target_ms), "LAST_CAUSAL_FRESH"
    following = _first_at_or_after(
        rows,
        target_ms,
        max_delay_ms=max_delay_ms,
        times=times,
    )
    if following is None:
        return None
    observed_ms = float(following.get("ts_ms") or 0)
    return following, observed_ms, "NEXT_OBSERVED_BOUNDED"


def _mid(book: Mapping[str, Any]) -> float:
    return 0.5 * (float(book["bid"]) + float(book["ask"]))


def _trade_identity(event: Mapping[str, Any]) -> str:
    payload = {
        "coin": event.get("coin"),
        "direction": event.get("direction"),
        "trigger_ts_ms": event.get("trigger_ts_ms"),
        "entry_ts_ms": event.get("entry_ts_ms"),
        "exit_ts_ms": event.get("exit_ts_ms"),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _settle(
    *,
    coin: str,
    direction: int,
    trigger_ts_ms: int,
    detection_book: Mapping[str, Any],
    entry_book: Mapping[str, Any],
    exit_book: Mapping[str, Any],
    entry_execution_ts_ms: float,
    exit_execution_ts_ms: float,
    notional_usd: float,
    fee_bps: float,
    measured_latency_ms: float,
    entry_book_selection: str,
    exit_book_selection: str,
) -> dict[str, Any]:
    entry_mid = _mid(entry_book)
    exit_mid = _mid(exit_book)
    detection_mid = _mid(detection_book)
    if direction > 0:
        entry_px = float(entry_book["ask"])
        exit_px = float(exit_book["bid"])
        entry_capacity = float(entry_book.get("ask_top_usd") or 0.0)
        exit_capacity = float(exit_book.get("bid_top_usd") or 0.0)
        executable_before_fees_bps = (exit_px - entry_px) / entry_px * 1e4
    else:
        entry_px = float(entry_book["bid"])
        exit_px = float(exit_book["ask"])
        entry_capacity = float(entry_book.get("bid_top_usd") or 0.0)
        exit_capacity = float(exit_book.get("ask_top_usd") or 0.0)
        executable_before_fees_bps = (entry_px - exit_px) / entry_px * 1e4

    gross_entry_bps = float(direction) * (exit_mid - entry_mid) / entry_mid * 1e4
    spread_cost_bps = gross_entry_bps - executable_before_fees_bps
    # The execution price is selected *after* measured latency. Charging another
    # latency stress here would double count the same delay.
    latency_cost_bps = 0.0
    slippage_bps = 0.0
    capacity_ratio = min(entry_capacity, exit_capacity) / float(notional_usd)
    full_fill = capacity_ratio >= 1.0
    net_bps = executable_before_fees_bps - float(fee_bps)
    gross_usd = gross_entry_bps / 1e4 * float(notional_usd)
    fees_usd = float(fee_bps) / 1e4 * float(notional_usd)
    spread_usd = spread_cost_bps / 1e4 * float(notional_usd)
    slippage_usd = slippage_bps / 1e4 * float(notional_usd)
    latency_usd = latency_cost_bps / 1e4 * float(notional_usd)
    pnl_usd = executable_before_fees_bps / 1e4 * float(notional_usd) - fees_usd
    reconciled = math.isclose(
        gross_usd - fees_usd - spread_usd - slippage_usd - latency_usd,
        pnl_usd,
        abs_tol=1e-7,
    )
    cost_component_receipts = {
        "fees": CostComponentReceipt(
            component="fees",
            amount_usd=fees_usd,
            zero_reason=ZeroCostReason.MEASURED_ZERO if fees_usd == 0.0 else None,
            formula_id="lead_lag.round_trip_fee.v1",
            reality_model_version="lead_lag_delayed_executable_bbo.v2",
            provenance_ids=("lead_lag.round_trip_fee_bps", "lead_lag.paper_notional_usd"),
        ).as_dict(),
        "spread": CostComponentReceipt(
            component="spread",
            amount_usd=spread_usd,
            zero_reason=ZeroCostReason.MEASURED_ZERO if spread_usd == 0.0 else None,
            formula_id="lead_lag.executable_bid_ask_spread.v1",
            reality_model_version="lead_lag_delayed_executable_bbo.v2",
            provenance_ids=("entry_book.bid_ask", "exit_book.bid_ask"),
        ).as_dict(),
        "slippage": CostComponentReceipt(
            component="slippage",
            amount_usd=slippage_usd,
            zero_reason=ZeroCostReason.NOT_APPLICABLE,
            formula_id="lead_lag.full_top_capacity.v1",
            reality_model_version="lead_lag_delayed_executable_bbo.v2",
            provenance_ids=("entry_capacity_usd", "exit_capacity_usd"),
        ).as_dict(),
        "latency": CostComponentReceipt(
            component="latency",
            amount_usd=latency_usd,
            zero_reason=ZeroCostReason.EMBEDDED_IN_EXECUTABLE_PRICE,
            formula_id="lead_lag.delayed_entry_price.v1",
            reality_model_version="lead_lag_delayed_executable_bbo.v2",
            provenance_ids=("measured_runtime_latency_ms", "entry_book_observed_ts_ms"),
        ).as_dict(),
    }
    event = {
        "coin": str(coin).upper(),
        "direction": int(direction),
        "trigger_ts_ms": int(trigger_ts_ms),
        "entry_ts_ms": int(math.ceil(entry_execution_ts_ms)),
        "exit_ts_ms": int(math.ceil(exit_execution_ts_ms)),
        "entry_book_observed_ts_ms": int(entry_book["ts_ms"]),
        "exit_book_observed_ts_ms": int(exit_book["ts_ms"]),
        "detection_mid": detection_mid,
        "entry_mid": entry_mid,
        "exit_mid": exit_mid,
        "entry_px": entry_px,
        "exit_px": exit_px,
        "entry_capacity_usd": entry_capacity,
        "exit_capacity_usd": exit_capacity,
        "capacity_ratio": capacity_ratio,
        "gross_bps": gross_entry_bps,
        "fees_bps": float(fee_bps),
        "spread_bps": spread_cost_bps,
        "slippage_bps": slippage_bps,
        "latency_bps": latency_cost_bps,
        "net_bps": net_bps,
        "gross_pnl_usd": gross_usd,
        "fees_usd": fees_usd,
        "spread_cost_usd": spread_usd,
        "slippage_cost_usd": slippage_usd,
        "latency_cost_usd": latency_usd,
        "cost_component_receipts": cost_component_receipts,
        "slippage_zero_reason": ZeroCostReason.NOT_APPLICABLE.value,
        "latency_zero_reason": ZeroCostReason.EMBEDDED_IN_EXECUTABLE_PRICE.value,
        "pnl_usd": pnl_usd,
        "measured_runtime_latency_ms": float(measured_latency_ms),
        "actual_entry_delay_ms": float(entry_execution_ts_ms) - float(trigger_ts_ms),
        "entry_book_age_ms": float(entry_execution_ts_ms) - float(entry_book["ts_ms"]),
        "exit_book_age_ms": float(exit_execution_ts_ms) - float(exit_book["ts_ms"]),
        "entry_book_selection": str(entry_book_selection),
        "exit_book_selection": str(exit_book_selection),
        "latency_embedded_in_entry_price": True,
        "top_level_capacity_measured": True,
        "full_fill": full_fill,
        "economic_reconciled": reconciled,
        "LIQUIDATABLE_NET": bool(full_fill and reconciled),
        "paper_read_only": True,
        "real_execution": False,
    }
    event["trade_id"] = _trade_identity(event)
    return event
