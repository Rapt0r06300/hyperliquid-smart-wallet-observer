from __future__ import annotations


def backoff_seconds(attempt: int, *, base: float = 1.0, maximum: float = 30.0) -> float:
    return min(maximum, base * (2 ** max(0, attempt - 1)))
