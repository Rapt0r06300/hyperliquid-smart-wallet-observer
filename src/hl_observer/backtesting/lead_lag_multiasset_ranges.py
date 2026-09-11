"""Frozen wall-clock range selection for multi-asset Lead-Lag research."""

from __future__ import annotations

import bisect
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from hl_observer.backtesting.lead_lag_source_alignment import (
    _merge_ranges,
)


def in_ranges(timestamp_ms: int, ranges: Sequence[tuple[int, int]]) -> bool:
    if not ranges:
        return False
    starts = [item[0] for item in ranges]
    index = bisect.bisect_right(starts, int(timestamp_ms)) - 1
    return index >= 0 and int(timestamp_ms) <= ranges[index][1]


def training_ranges(
    root: str | Path,
    *,
    train_fraction: float,
    window_discovery: Callable[[str | Path], Sequence[Any]],
) -> tuple[list[tuple[int, int]], dict[str, Any]]:
    merged = _merge_ranges(window_discovery(root))
    if not merged:
        return [], {
            "status": "NO_MARKET_WINDOWS",
            "full_start_ms": None,
            "full_end_ms": None,
            "train_end_ms": None,
            "train_fraction": train_fraction,
        }
    start_ms = merged[0][0]
    end_ms = merged[-1][1]
    train_end = int(start_ms + (end_ms - start_ms) * train_fraction)
    train_ranges: list[tuple[int, int]] = []
    for start, end in merged:
        if start > train_end:
            break
        train_ranges.append((start, min(end, train_end)))
    return train_ranges, {
        "status": "TRAIN_CUT_FROZEN_FROM_WALL_CLOCK",
        "full_start_ms": start_ms,
        "full_end_ms": end_ms,
        "train_end_ms": train_end,
        "train_fraction": train_fraction,
        "full_merged_ranges": [list(item) for item in merged],
        "train_ranges": [list(item) for item in train_ranges],
        "heldout_start_ms": train_end + 1,
    }


__all__ = ["in_ranges", "training_ranges"]
