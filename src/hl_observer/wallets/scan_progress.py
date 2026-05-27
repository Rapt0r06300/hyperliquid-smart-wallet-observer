from __future__ import annotations


def progress_percent(done: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(max(0.0, min(100.0, done / total * 100.0)), 2)
