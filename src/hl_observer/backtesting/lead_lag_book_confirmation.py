"""Causal Hyperliquid book confirmation for external Lead-Lag shocks.

The helper is selection-only.  It joins every external shock to the latest
Hyperliquid top-of-book from the same recorded shard that was observable no
later than the shock.  Future, stale, invalid and cross-shard books fail closed.
"""

from __future__ import annotations

import bisect
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = "hypersmart.lead_lag_book_confirmation.v1"
MECHANISM = "lead_lag_v9_external_shock_book_confirmation_taker"
SHOCK_WINDOWS_MS = (250, 1_000)
SHOCK_THRESHOLDS_BPS = (4.0, 8.0, 12.0)
IMBALANCE_THRESHOLDS = (0.15, 0.35)
HORIZONS_MS = (1_000, 5_000, 15_000)
MAX_BOOK_AGE_MS = 250
MIN_TRAIN_FILLS = 30


def book_confirmation_trial_count(coin_count: int) -> int:
    """Return the complete fixed family size before any replay is run."""

    return max(0, int(coin_count)) * (
        len(SHOCK_WINDOWS_MS)
        * len(SHOCK_THRESHOLDS_BPS)
        * len(IMBALANCE_THRESHOLDS)
        * len(HORIZONS_MS)
    )


def _normalise_trade_sources(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[list[int], list[tuple[int, str]]]:
    values: list[tuple[int, str]] = []
    for row in rows:
        try:
            timestamp_ms = int(row.get("observable_at_ms"))
        except (TypeError, ValueError, OverflowError):
            continue
        source_id = str(row.get("source_id") or "")
        if timestamp_ms >= 0 and source_id:
            values.append((timestamp_ms, source_id))
    values.sort()
    return [row[0] for row in values], values


def _normalise_books(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, tuple[list[int], list[tuple[int, float]]]], int]:
    grouped: dict[str, list[tuple[int, float]]] = defaultdict(list)
    invalid = 0
    for row in rows:
        try:
            timestamp_ms = int(row.get("observable_at_ms", row.get("ts_ms")))
            bid_size = float(row.get("bid_size"))
            ask_size = float(row.get("ask_size"))
        except (TypeError, ValueError, OverflowError):
            invalid += 1
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
            invalid += 1
            continue
        grouped[source_id].append((timestamp_ms, (bid_size - ask_size) / total))
    result: dict[str, tuple[list[int], list[tuple[int, float]]]] = {}
    for source_id, values in grouped.items():
        values.sort()
        result[source_id] = ([row[0] for row in values], values)
    return result, invalid


def confirm_shocks_with_causal_book(
    shocks: Sequence[tuple[int, float]],
    books: Sequence[Mapping[str, Any]],
    trade_observations: Sequence[Mapping[str, Any]],
    *,
    min_abs_imbalance: float,
    max_book_age_ms: int,
) -> tuple[list[tuple[int, float]], dict[str, Any]]:
    """Keep shocks whose causal same-shard book imbalance agrees in direction."""

    threshold = float(min_abs_imbalance)
    max_age = int(max_book_age_ms)
    if not math.isfinite(threshold) or threshold < 0.0 or threshold > 1.0:
        raise ValueError("min_abs_imbalance must be finite and within [0, 1]")
    if max_age < 0:
        raise ValueError("max_book_age_ms must be non-negative")

    trade_timestamps, trade_rows = _normalise_trade_sources(trade_observations)
    books_by_source, invalid_book_rows = _normalise_books(books)
    accepted: list[tuple[int, float]] = []
    counts = {
        "candidate_shocks": len(shocks),
        "accepted": 0,
        "missing_trade_source": 0,
        "missing_same_source_book": 0,
        "stale_book": 0,
        "book_conflict": 0,
        "invalid_direction": 0,
        "invalid_book_rows": invalid_book_rows,
    }

    for timestamp_ns, raw_direction in shocks:
        timestamp_ms = int(timestamp_ns) // 1_000_000
        direction = 1.0 if float(raw_direction) > 0.0 else -1.0 if float(raw_direction) < 0.0 else 0.0
        if direction == 0.0:
            counts["invalid_direction"] += 1
            continue
        trade_index = bisect.bisect_right(trade_timestamps, timestamp_ms) - 1
        if trade_index < 0 or trade_rows[trade_index][0] != timestamp_ms:
            counts["missing_trade_source"] += 1
            continue
        source_id = trade_rows[trade_index][1]
        source_books = books_by_source.get(source_id)
        if source_books is None:
            counts["missing_same_source_book"] += 1
            continue
        book_timestamps, book_rows = source_books
        book_index = bisect.bisect_right(book_timestamps, timestamp_ms) - 1
        if book_index < 0:
            counts["missing_same_source_book"] += 1
            continue
        book_timestamp_ms, imbalance = book_rows[book_index]
        if timestamp_ms - book_timestamp_ms > max_age:
            counts["stale_book"] += 1
            continue
        if direction * imbalance + 1e-12 < threshold:
            counts["book_conflict"] += 1
            continue
        accepted.append((int(timestamp_ns), direction))
        counts["accepted"] += 1

    return accepted, {
        "schema_version": SCHEMA_VERSION,
        "mechanism": MECHANISM,
        "min_abs_imbalance": threshold,
        "max_book_age_ms": max_age,
        **counts,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_loaded": False,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "HORIZONS_MS",
    "IMBALANCE_THRESHOLDS",
    "MAX_BOOK_AGE_MS",
    "MECHANISM",
    "MIN_TRAIN_FILLS",
    "SCHEMA_VERSION",
    "SHOCK_THRESHOLDS_BPS",
    "SHOCK_WINDOWS_MS",
    "book_confirmation_trial_count",
    "confirm_shocks_with_causal_book",
]
