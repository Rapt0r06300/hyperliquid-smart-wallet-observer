from __future__ import annotations

from math import sqrt


def wilson_lower_bound(wins: int, total: int, z: float = 1.96) -> float:
    if total <= 0:
        return 0.0
    phat = wins / total
    denominator = 1 + z * z / total
    centre = phat + z * z / (2 * total)
    margin = z * sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    return (centre - margin) / denominator


def one_big_win_dependency(top_trade_pnl_share: float, threshold: float = 0.30) -> bool:
    return top_trade_pnl_share > threshold
