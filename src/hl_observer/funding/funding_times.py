"""Funding schedule helpers."""

from __future__ import annotations


def next_funding_time_ms(now_ms: int, *, interval_hours: int = 8) -> int:
    interval_ms = int(interval_hours) * 60 * 60 * 1000
    return ((int(now_ms) // interval_ms) + 1) * interval_ms


__all__ = ["next_funding_time_ms"]
