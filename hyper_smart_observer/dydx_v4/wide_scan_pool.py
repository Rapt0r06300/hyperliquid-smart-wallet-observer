from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WideScanPlan:
    selected: list[tuple[str, float]]
    next_cursor: int
    candidate_count: int
    anchor_count: int
    rotated_count: int


def select_rotating_wallets(
    pairs: list[tuple[str, float]],
    hot_capacity: int = 2500,
    rotate_batch: int = 750,
    cursor: int = 0,
    anchor_share: float = 0.50,
) -> WideScanPlan:
    if not pairs:
        return WideScanPlan([], 0, 0, 0, 0)
    capacity = max(1, int(hot_capacity))
    anchor_n = max(1, min(len(pairs), int(capacity * max(0.10, min(0.90, anchor_share)))))
    top = pairs[:anchor_n]
    rest = pairs[anchor_n:]
    if not rest:
        return WideScanPlan(top[:capacity], cursor, len(pairs), len(top[:capacity]), 0)
    batch_n = max(1, min(int(rotate_batch), capacity - len(top), len(rest)))
    start = int(cursor or 0) % len(rest)
    rotated = rest[start:start + batch_n]
    if len(rotated) < batch_n:
        rotated += rest[:batch_n - len(rotated)]
    next_cursor = (start + batch_n) % len(rest)
    merged: dict[str, float] = {}
    for addr, score in top + rotated:
        merged[str(addr)] = max(float(score or 0.0), merged.get(str(addr), 0.0))
    selected = sorted(merged.items(), key=lambda x: x[1], reverse=True)[:capacity]
    return WideScanPlan(selected, next_cursor, len(pairs), len(top), len(rotated))


__all__ = ["WideScanPlan", "select_rotating_wallets"]
