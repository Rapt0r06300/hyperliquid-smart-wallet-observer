"""Causal trade-flow + book confirmation for Lead-Lag TRAIN research.

A lead shock is retained only when two already-observed microstructure surfaces
agree with its direction: same-shard follower-book imbalance and signed lead
aggressor notional over a fixed backward-looking window.  No future event is
used and this helper never submits orders.
"""
from __future__ import annotations

import bisect
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "hypersmart.lead_lag_microstructure_confirmation.v1"
MECHANISM = "lead_lag_v10_external_shock_book_flow_confirmation_taker"
SHOCK_WINDOWS_MS = (250, 1_000)
SHOCK_THRESHOLDS_BPS = (4.0, 8.0, 12.0)
HORIZONS_MS = (1_000, 5_000, 15_000)
FLOW_LOOKBACK_MS = 1_000
MIN_BOOK_IMBALANCE = 0.15
MIN_FLOW_IMBALANCE = 0.15
MIN_FLOW_TRADES = 3
MAX_BOOK_AGE_MS = 250
MIN_TRAIN_FILLS = 30
NOTIONALS_USD = (25.0, 75.0, 150.0, 300.0)
ECONOMIC_TARGET_USD_DAY = 4.0


def trial_count(coin_count: int) -> int:
    return max(0, int(coin_count)) * (
        len(SHOCK_WINDOWS_MS)
        * len(SHOCK_THRESHOLDS_BPS)
        * len(HORIZONS_MS)
        * len(NOTIONALS_USD)
    )


def _normalise_books(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, tuple[list[int], list[tuple[int, float]]]]:
    grouped: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for row in rows:
        try:
            timestamp_ms = int(row.get("observable_at_ms", row.get("ts_ms")))
            bid_size = float(row.get("bid_size"))
            ask_size = float(row.get("ask_size"))
        except (TypeError, ValueError, OverflowError):
            continue
        source_id = str(row.get("source_id") or "")
        total = bid_size + ask_size
        if (
            timestamp_ms < 0
            or not source_id
            or not all(math.isfinite(value) for value in (bid_size, ask_size))
            or bid_size <= 0.0
            or ask_size <= 0.0
            or total <= 0.0
        ):
            continue
        grouped[source_id].append(
            (timestamp_ms, (bid_size - ask_size) / total)
        )
    result: dict[str, tuple[list[int], list[tuple[int, float]]]] = {}
    for source_id, values in grouped.items():
        values.sort()
        result[source_id] = ([value[0] for value in values], values)
    return result


def _normalise_trades(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[int], list[dict[str, Any]]]:
    values: list[dict[str, Any]] = []
    for row in rows:
        try:
            timestamp_ms = int(row.get("observable_at_ms"))
            price = float(row.get("price"))
            qty = float(row.get("qty"))
            direction = float(row.get("direction"))
        except (TypeError, ValueError, OverflowError):
            continue
        source_id = str(row.get("source_id") or "")
        if (
            timestamp_ms < 0
            or not source_id
            or not math.isfinite(price)
            or not math.isfinite(qty)
            or not math.isfinite(direction)
            or price <= 0.0
            or qty <= 0.0
            or direction == 0.0
        ):
            continue
        values.append(
            {
                "observable_at_ms": timestamp_ms,
                "source_id": source_id,
                "price": price,
                "qty": qty,
                "direction": 1.0 if direction > 0.0 else -1.0,
            }
        )
    values.sort(
        key=lambda row: (
            int(row["observable_at_ms"]),
            str(row["source_id"]),
            float(row["price"]),
        )
    )
    return [int(row["observable_at_ms"]) for row in values], values


def confirm_shocks_with_book_and_flow(
    shocks: Sequence[tuple[int, float]],
    books: Sequence[Mapping[str, Any]],
    trade_observations: Sequence[Mapping[str, Any]],
    *,
    flow_lookback_ms: int = FLOW_LOOKBACK_MS,
    min_book_imbalance: float = MIN_BOOK_IMBALANCE,
    min_flow_imbalance: float = MIN_FLOW_IMBALANCE,
    min_flow_trades: int = MIN_FLOW_TRADES,
    max_book_age_ms: int = MAX_BOOK_AGE_MS,
) -> tuple[list[tuple[int, float]], dict[str, Any]]:
    """Keep only shocks causally corroborated by book and signed trade flow."""

    lookback = int(flow_lookback_ms)
    min_trades = int(min_flow_trades)
    if lookback <= 0 or min_trades <= 0:
        raise ValueError("flow lookback and minimum trade count must be positive")
    for name, value in (
        ("min_book_imbalance", min_book_imbalance),
        ("min_flow_imbalance", min_flow_imbalance),
    ):
        numeric = float(value)
        if not math.isfinite(numeric) or numeric < 0.0 or numeric > 1.0:
            raise ValueError(f"{name} must be finite and within [0, 1]")

    books_by_source = _normalise_books(books)
    trade_times, trades = _normalise_trades(trade_observations)
    accepted: list[tuple[int, float]] = []
    counts: dict[str, int] = defaultdict(int)
    counts["candidate_shocks"] = len(shocks)

    for timestamp_ns, raw_direction in shocks:
        timestamp_ms = int(timestamp_ns) // 1_000_000
        direction = 1.0 if float(raw_direction) > 0 else -1.0 if float(raw_direction) < 0 else 0.0
        if direction == 0.0:
            counts["invalid_direction"] += 1
            continue

        right = bisect.bisect_right(trade_times, timestamp_ms)
        exact = [
            row
            for row in trades[max(0, right - 16):right]
            if int(row["observable_at_ms"]) == timestamp_ms
        ]
        if not exact:
            counts["missing_trigger_source"] += 1
            continue
        source_id = str(exact[-1]["source_id"])

        source_books = books_by_source.get(source_id)
        if source_books is None:
            counts["missing_same_source_book"] += 1
            continue
        book_times, book_rows = source_books
        book_index = bisect.bisect_right(book_times, timestamp_ms) - 1
        if book_index < 0:
            counts["missing_same_source_book"] += 1
            continue
        book_ts, book_imbalance = book_rows[book_index]
        if timestamp_ms - book_ts > int(max_book_age_ms):
            counts["stale_book"] += 1
            continue
        if direction * float(book_imbalance) + 1e-12 < float(min_book_imbalance):
            counts["book_conflict"] += 1
            continue

        left = bisect.bisect_left(trade_times, timestamp_ms - lookback)
        window = [
            row
            for row in trades[left:right]
            if str(row["source_id"]) == source_id
            and int(row["observable_at_ms"]) <= timestamp_ms
        ]
        if len(window) < min_trades:
            counts["insufficient_flow_trades"] += 1
            continue
        signed = sum(
            float(row["direction"]) * float(row["price"]) * float(row["qty"])
            for row in window
        )
        absolute = sum(
            float(row["price"]) * float(row["qty"])
            for row in window
        )
        if absolute <= 0.0:
            counts["unmeasurable_flow"] += 1
            continue
        flow_imbalance = signed / absolute
        if direction * flow_imbalance + 1e-12 < float(min_flow_imbalance):
            counts["flow_conflict"] += 1
            continue

        accepted.append((int(timestamp_ns), direction))
        counts["accepted"] += 1

    return accepted, {
        "schema_version": SCHEMA_VERSION,
        "mechanism": MECHANISM,
        "flow_lookback_ms": lookback,
        "min_book_imbalance": float(min_book_imbalance),
        "min_flow_imbalance": float(min_flow_imbalance),
        "min_flow_trades": min_trades,
        "max_book_age_ms": int(max_book_age_ms),
        **dict(counts),
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_loaded": False,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "FLOW_LOOKBACK_MS",
    "HORIZONS_MS",
    "MAX_BOOK_AGE_MS",
    "MECHANISM",
    "MIN_BOOK_IMBALANCE",
    "MIN_FLOW_IMBALANCE",
    "MIN_FLOW_TRADES",
    "MIN_TRAIN_FILLS",
    "NOTIONALS_USD",
    "ECONOMIC_TARGET_USD_DAY",
    "SHOCK_THRESHOLDS_BPS",
    "SHOCK_WINDOWS_MS",
    "confirm_shocks_with_book_and_flow",
    "trial_count",
]
