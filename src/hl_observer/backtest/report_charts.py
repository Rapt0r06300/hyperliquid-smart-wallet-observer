"""Backtest report series (V12 capability R, repo 11): equity/PnL/drawdown/Sharpe/Brier.

Computes the report series from REAL realized PnLs / probabilities (caller-supplied).
Pure math, no fabrication; honest empty results on empty input.
"""

from __future__ import annotations

from math import sqrt


def equity_curve(realized_pnls: list[float], *, start_equity: float = 1000.0) -> list[float]:
    eq = float(start_equity)
    out = [eq]
    for p in realized_pnls:
        eq += float(p)
        out.append(round(eq, 6))
    return out


def drawdown_series(equity: list[float]) -> list[float]:
    peak = float("-inf")
    out: list[float] = []
    for e in equity:
        peak = max(peak, e)
        out.append(round(e - peak, 6))      # <= 0
    return out


def max_drawdown(equity: list[float]) -> float:
    dd = drawdown_series(equity)
    return min(dd) if dd else 0.0


def sharpe(returns: list[float], *, periods_per_year: int = 1) -> float:
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)
    sd = sqrt(var)
    if sd == 0:
        return 0.0
    return round(mean / sd * sqrt(periods_per_year), 6)


def brier_advantage(probs: list[float], outcomes: list[int], *, baseline: float = 0.5) -> float:
    """Positive = model probabilities beat a fixed-baseline forecaster (lower Brier is better)."""
    n = min(len(probs), len(outcomes))
    if n == 0:
        return 0.0
    model = sum((float(probs[i]) - int(outcomes[i])) ** 2 for i in range(n)) / n
    base = sum((baseline - int(outcomes[i])) ** 2 for i in range(n)) / n
    return round(base - model, 6)


def build_report(realized_pnls: list[float], *, start_equity: float = 1000.0) -> dict:
    eq = equity_curve(realized_pnls, start_equity=start_equity)
    rets = [float(p) for p in realized_pnls]
    return {
        "equity": eq,
        "drawdown": drawdown_series(eq),
        "max_drawdown": max_drawdown(eq),
        "sharpe": sharpe(rets),
        "total_pnl": round(sum(rets), 6),
        "trades": len(rets),
        "final_equity": eq[-1] if eq else round(start_equity, 6),
        "empty": not rets,
    }


__all__ = ["equity_curve", "drawdown_series", "max_drawdown", "sharpe", "brier_advantage", "build_report"]
