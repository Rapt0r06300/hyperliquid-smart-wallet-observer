from __future__ import annotations


def detect_one_big_win(pnls: list[float], threshold: float = 0.6) -> bool:
    positive_total = sum(value for value in pnls if value > 0)
    if positive_total <= 0:
        return False
    return max((value for value in pnls if value > 0), default=0.0) / positive_total > threshold
