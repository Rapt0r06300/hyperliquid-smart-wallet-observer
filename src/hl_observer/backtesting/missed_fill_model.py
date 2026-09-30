"""Missed-fill guard for delayed or illiquid paper entries."""

from __future__ import annotations


def is_missed_fill(*, age_ms: int, max_age_ms: int, partial_ratio: float) -> bool:
    return int(age_ms) > int(max_age_ms) or float(partial_ratio) <= 0.0


__all__ = ["is_missed_fill"]
