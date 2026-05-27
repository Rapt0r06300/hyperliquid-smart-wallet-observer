from __future__ import annotations


def pnl_concentration_score(pnls: list[float]) -> float:
    usable = [abs(value) for value in pnls if value != 0]
    if not usable:
        return 0.0
    concentration = max(usable) / sum(usable)
    return max(0.0, min(100.0, 100.0 * (1.0 - concentration)))
