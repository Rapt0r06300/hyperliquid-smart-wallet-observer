"""TRAIN-only signed public-trade adapter for Lead-Lag maker research.

The canonical Hyperliquid tick store already records public ``trades`` frames
with durable observable clocks and aggressor side.  This module exposes only
those recorded PAPER/READ-ONLY rows inside physically clamped TRAIN windows so
maker queue research never needs to read validation/OOS/forward data.
"""
from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.simulation.lead_lag_l2_history import load_market_microstructure_history

SCHEMA_VERSION = "hypersmart.lead_lag_maker_train_data.v1"


def _normalized_ranges(
    train_ranges: Sequence[Sequence[int]],
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for raw in train_ranges:
        if len(raw) < 2:
            continue
        try:
            start_ms = int(raw[0])
            end_ms = int(raw[1])
        except (TypeError, ValueError, OverflowError):
            continue
        if start_ms <= 0 or end_ms < start_ms:
            continue
        ranges.append((start_ms, end_ms))
    ranges.sort()
    merged: list[tuple[int, int]] = []
    for start_ms, end_ms in ranges:
        if not merged or start_ms > merged[-1][1] + 1:
            merged.append((start_ms, end_ms))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end_ms))
    return merged


def _contains(timestamp_ms: int, ranges: Sequence[tuple[int, int]]) -> bool:
    return any(start_ms <= timestamp_ms <= end_ms for start_ms, end_ms in ranges)


def _clipped_event_windows(
    event_ts_ms: Sequence[int],
    train_ranges: Sequence[tuple[int, int]],
    *,
    before_ms: int,
    after_ms: int,
) -> tuple[list[tuple[int, int]], int]:
    windows: list[tuple[int, int]] = []
    events_rejected = 0
    before = max(0, int(before_ms))
    after = max(0, int(after_ms))
    for raw_timestamp in event_ts_ms:
        try:
            timestamp_ms = int(raw_timestamp)
        except (TypeError, ValueError, OverflowError):
            events_rejected += 1
            continue
        containing = next(
            (
                (start_ms, end_ms)
                for start_ms, end_ms in train_ranges
                if start_ms <= timestamp_ms <= end_ms
            ),
            None,
        )
        if containing is None:
            events_rejected += 1
            continue
        train_start, train_end = containing
        windows.append(
            (
                max(train_start, timestamp_ms - before),
                min(train_end, timestamp_ms + after),
            )
        )

    windows.sort()
    merged: list[tuple[int, int]] = []
    for start_ms, end_ms in windows:
        if not merged or start_ms > merged[-1][1] + 1:
            merged.append((start_ms, end_ms))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end_ms))
    return merged, events_rejected


def _positive(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number > 0.0 else None


def _safe_recorded_trade(row: Mapping[str, Any]) -> bool:
    try:
        timestamp_ms = int(row.get("ts_ms") or 0)
    except (TypeError, ValueError, OverflowError):
        return False
    return bool(
        timestamp_ms > 0
        and str(row.get("coin") or "").strip()
        and str(row.get("side") or "").upper() in {"A", "B"}
        and _positive(row.get("px")) is not None
        and _positive(row.get("sz")) is not None
        and str(row.get("trade_id") or "").strip()
        and str(row.get("source") or "") == "hyperliquid:recorded:trades"
        and str(row.get("data_origin") or "") == "RECORDED_REAL"
        and row.get("read_only") is True
        and row.get("real_execution") is False
    )


def load_train_public_trade_history(
    root: str | Path,
    event_ts_ms: Sequence[int],
    *,
    train_ranges: Sequence[Sequence[int]],
    before_ms: int = 1_000,
    after_ms: int = 17_000,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Load signed Hyperliquid public trades without reading beyond TRAIN.

    Each sparse event window is intersected with its containing TRAIN range
    *before* the canonical tick-store loader is called.  The underlying loader
    therefore receives explicit ``start_ms``/``end_ms`` bounds, and returned
    rows are defensively checked again before they can reach maker queue logic.
    """

    normalized_ranges = _normalized_ranges(train_ranges)
    windows, events_rejected = _clipped_event_windows(
        event_ts_ms,
        normalized_ranges,
        before_ms=before_ms,
        after_ms=after_ms,
    )
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    duplicates = invalid_or_unsafe = outside_train = 0
    unverified_source_windows = 0
    source_rows_seen = 0
    source_metadata: list[dict[str, Any]] = []

    for start_ms, end_ms in windows:
        _books, trades, meta = load_market_microstructure_history(
            root,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        meta_dict = dict(meta or {})
        source_metadata.append(meta_dict)
        if (
            meta_dict.get("source_time_filter_applied") is not True
            or meta_dict.get("real_execution") is not False
        ):
            unverified_source_windows += 1
            continue
        for raw_rows in trades.values():
            for raw_row in raw_rows:
                source_rows_seen += 1
                if not isinstance(raw_row, Mapping) or not _safe_recorded_trade(raw_row):
                    invalid_or_unsafe += 1
                    continue
                row = dict(raw_row)
                timestamp_ms = int(row["ts_ms"])
                if (
                    timestamp_ms < start_ms
                    or timestamp_ms > end_ms
                    or not _contains(timestamp_ms, normalized_ranges)
                ):
                    outside_train += 1
                    continue
                coin = str(row["coin"]).upper()
                identity = (coin, str(row["trade_id"]))
                if identity in seen:
                    duplicates += 1
                    continue
                seen.add(identity)
                result[coin].append(row)

    finalized = dict(result)
    for rows in finalized.values():
        rows.sort(key=lambda row: (int(row["ts_ms"]), str(row["trade_id"])))

    return finalized, {
        "schema_version": SCHEMA_VERSION,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "train_ranges": [list(item) for item in normalized_ranges],
        "source_windows": [list(item) for item in windows],
        "events_rejected_outside_train": events_rejected,
        "source_rows_seen": source_rows_seen,
        "trade_rows": sum(len(rows) for rows in finalized.values()),
        "coins_with_trades": sorted(finalized),
        "duplicate_trades_rejected": duplicates,
        "invalid_or_unsafe_trades_rejected": invalid_or_unsafe,
        "rows_rejected_outside_train": outside_train,
        "unverified_source_windows_rejected": unverified_source_windows,
        "source_time_filter_verified": unverified_source_windows == 0,
        "source_metadata": source_metadata,
        "heldout_loaded": False,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = ["SCHEMA_VERSION", "load_train_public_trade_history"]
