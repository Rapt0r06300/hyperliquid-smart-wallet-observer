from __future__ import annotations


def calculate_max_drawdown(equity_curve: list[float]) -> float | None:
    if not equity_curve:
        return None
    peak = equity_curve[0]
    max_drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        drawdown = peak - value
        max_drawdown = max(max_drawdown, drawdown)
    return max_drawdown
