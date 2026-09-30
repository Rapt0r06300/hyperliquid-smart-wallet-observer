from __future__ import annotations


def time_stop_triggered(age_ms: int, max_hold_ms: int) -> bool:
    return age_ms >= max_hold_ms
