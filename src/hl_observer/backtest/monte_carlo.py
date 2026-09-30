from __future__ import annotations


def bootstrap_mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)
