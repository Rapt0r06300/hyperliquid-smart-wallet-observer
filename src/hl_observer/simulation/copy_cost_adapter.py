"""Executable cost evidence for Copy-Vault paper evaluation.

Copy historical candle returns enter *after* the configured copy delay. The
latency degradation is therefore embedded in the delayed-entry gross return and
must not be subtracted twice. Spread and extra depth slippage can become
measured only when Hyperliquid top-of-book observations are causally available
at or before both entry and exit and cover the paper notional.
"""
from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Mapping
from typing import Any

from hl_observer.instrument_identity import preserve_native_instrument_symbol
from hl_observer.simulation.cross_venue_depth_adapter import DEFAULT_DEPTH_FRESHNESS_MS

COPY_ROUNDTRIP_TAKER_FEES_BPS = 9.0  # 4.5 bps entry + 4.5 bps exit


def _number(value: object) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def _at_or_before(
    rows: list[dict[str, Any]],
    times: list[int],
    target_ms: float,
    *,
    freshness_ms: float,
) -> tuple[dict[str, Any] | None, float | None]:
    if not rows:
        return None, None
    index = bisect.bisect_right(times, int(target_ms)) - 1
    if index < 0:
        return None, None
    row = rows[index]
    age = float(target_ms) - float(row["_ts_ms"])
    if age < 0 or age > float(freshness_ms):
        return None, age
    return row, age


def _percentile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("empty percentile")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(math.ceil(q * len(ordered)) - 1)))
    return float(ordered[index])


def measure_copy_cost_components(
    events: Iterable[Mapping[str, Any]],
    depth_snapshots: Mapping[str, list[dict[str, Any]]],
    *,
    notional_usd: float,
    copy_delay_ms: float,
    horizon_ms: float,
    threshold: float,
    freshness_ms: float = DEFAULT_DEPTH_FRESHNESS_MS,
) -> dict[str, Any]:
    """Measure one conservative round-trip cost vector for selected Copy events.

    The returned ``components_bps`` is present only if EVERY selected event has
    causal entry+exit depth and enough top-level capacity. Spread uses the 95th
    percentile of observed round-trip half-spread sums. Additional slippage is
    then measured as zero because no deeper level is crossed at the requested
    notional. Missing evidence remains explicit and non-liquidatable. Events are
    processed as an iterator, and the depth rows/time index are cached once per
    instrument for this call so large candidate sets do not copy the same book.
    """
    spreads: list[float] = []
    failures: dict[str, int] = {}
    selected_count = 0
    matched = 0
    min_capacity = float("inf")
    max_depth_age: float | None = None
    rows_by_coin: dict[str, list[dict[str, Any]]] = {}
    times_by_coin: dict[str, list[int]] = {}

    def fail(reason: str) -> None:
        failures[reason] = failures.get(reason, 0) + 1

    for event in events:
        move_frac = _number(event.get("move_frac"))
        if move_frac is None or move_frac < float(threshold):
            continue
        selected_count += 1
        coin = preserve_native_instrument_symbol(event.get("coin"))
        ts = _number(event.get("ts_ms"))
        if ts is None:
            fail("EVENT_TIMESTAMP_MISSING")
            continue
        if coin not in rows_by_coin:
            rows = list(depth_snapshots.get(coin) or [])
            rows_by_coin[coin] = rows
            times_by_coin[coin] = [int(row["_ts_ms"]) for row in rows]
        rows = rows_by_coin[coin]
        times = times_by_coin[coin]
        if not rows:
            fail("DEPTH_MISSING")
            continue
        entry_target = ts + float(copy_delay_ms)
        exit_target = entry_target + float(horizon_ms)
        entry, entry_age = _at_or_before(rows, times, entry_target, freshness_ms=freshness_ms)
        exit_, exit_age = _at_or_before(rows, times, exit_target, freshness_ms=freshness_ms)
        if entry is None:
            fail("ENTRY_DEPTH_STALE_OR_FUTURE_ONLY")
            continue
        if exit_ is None:
            fail("EXIT_DEPTH_STALE_OR_FUTURE_ONLY")
            continue
        entry_capacity = _number(entry.get("_capacity_usd"))
        exit_capacity = _number(exit_.get("_capacity_usd"))
        if entry_capacity is None or entry_capacity < float(notional_usd):
            fail("ENTRY_TOP_CAPACITY_INSUFFICIENT")
            continue
        if exit_capacity is None or exit_capacity < float(notional_usd):
            fail("EXIT_TOP_CAPACITY_INSUFFICIENT")
            continue
        entry_half = _number(entry.get("hl_demi_spread_bps"))
        exit_half = _number(exit_.get("hl_demi_spread_bps"))
        if entry_half is None or exit_half is None or entry_half < 0 or exit_half < 0:
            fail("HL_SPREAD_MISSING")
            continue
        matched += 1
        spreads.append(entry_half + exit_half)
        min_capacity = min(min_capacity, entry_capacity, exit_capacity)
        event_max_age = max(float(entry_age or 0.0), float(exit_age or 0.0))
        max_depth_age = event_max_age if max_depth_age is None else max(max_depth_age, event_max_age)

    complete = selected_count > 0 and matched == selected_count and not failures
    components = None
    if complete:
        components = {
            "fees_bps": COPY_ROUNDTRIP_TAKER_FEES_BPS,
            "spread_bps": round(_percentile(spreads, 0.95), 6),
            "slippage_bps": 0.0,
            # The return function itself enters after copy_delay_ms. Latency
            # cannot be subtracted again without double-counting.
            "latency_bps": 0.0,
        }
    return {
        "schema_version": "hypersmart.copy_cost_evidence.v1",
        "selected_events": selected_count,
        "matched_events": matched,
        "complete": complete,
        "components_bps": components,
        "failure_counts": failures,
        "notional_usd": float(notional_usd),
        "copy_delay_ms": float(copy_delay_ms),
        "horizon_ms": float(horizon_ms),
        "threshold": float(threshold),
        "depth_freshness_ms": float(freshness_ms),
        "min_observed_top_capacity_usd": None if matched == 0 else round(min_capacity, 6),
        "max_depth_age_ms": max_depth_age,
        "spread_rule": "P95_ENTRY_HALF_PLUS_EXIT_HALF",
        "slippage_rule": "ZERO_ONLY_WHEN_TOP_CAPACITY_COVERS_NOTIONAL",
        "latency_rule": "EMBEDDED_IN_DELAYED_ENTRY_GROSS",
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = ["COPY_ROUNDTRIP_TAKER_FEES_BPS", "measure_copy_cost_components"]
