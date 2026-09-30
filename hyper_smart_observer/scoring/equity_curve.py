from __future__ import annotations

import math


def build_equity_curve_from_pnl(pnl_values: list[float]) -> list[float]:
    """Build a local cumulative PnL curve starting from zero."""

    curve = [0.0]
    running = 0.0
    for value in pnl_values:
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        running += float(value)
        curve.append(running)
    return curve


def pnl_returns_from_curve(equity_curve: list[float]) -> list[float]:
    if len(equity_curve) < 2:
        return []
    return [equity_curve[index] - equity_curve[index - 1] for index in range(1, len(equity_curve))]
