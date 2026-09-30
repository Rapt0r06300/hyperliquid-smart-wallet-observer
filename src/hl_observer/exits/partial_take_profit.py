from __future__ import annotations


def partial_take_profit_size(position_size: float, fraction: float = 0.5) -> float:
    return max(0.0, position_size * fraction)
