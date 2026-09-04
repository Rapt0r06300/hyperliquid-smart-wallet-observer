"""Pure deterministic temporal helpers for Lead-Lag shadow economics."""
from __future__ import annotations

import hashlib


def _placebo_direction(coin: str, signal_ts_ns: int) -> float:
    digest = hashlib.sha256(
        f"{coin}|{signal_ts_ns}|placebo-v1".encode()
    ).digest()
    return 1.0 if digest[0] & 1 else -1.0


def _temporal_bounds(
    signal_times: list[int], *, purge_ns: int
) -> dict[str, int | None]:
    ordered = sorted(set(int(value) for value in signal_times))
    if len(ordered) < 3:
        return {
            "train_end_ns": None,
            "validation_start_ns": None,
            "validation_end_ns": None,
            "oos_start_ns": None,
            "purge_ns": int(purge_ns),
        }
    train_index = min(
        len(ordered) - 2,
        max(0, int(len(ordered) * 0.60) - 1),
    )
    validation_index = min(
        len(ordered) - 1,
        max(train_index + 1, int(len(ordered) * 0.80) - 1),
    )
    train_end = ordered[train_index]
    validation_end = ordered[validation_index]
    return {
        "train_end_ns": train_end,
        "validation_start_ns": train_end + int(purge_ns),
        "validation_end_ns": validation_end,
        "oos_start_ns": validation_end + int(purge_ns),
        "purge_ns": int(purge_ns),
    }
