from __future__ import annotations


def pnl_concentration_ratio(pnls: list[float]) -> float:
    positives = [value for value in pnls if value > 0]
    total_positive = sum(positives)
    if total_positive <= 0:
        return 0.0
    return max(positives) / total_positive


def one_big_win_risk(pnls: list[float], *, threshold: float = 0.65) -> bool:
    return pnl_concentration_ratio(pnls) >= threshold
