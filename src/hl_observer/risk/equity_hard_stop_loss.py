"""Equity hard stop for paper portfolio."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EquityHardStopDecision:
    allow_new_entries: bool
    equity_usdt: float
    start_equity_usdt: float
    drawdown_pct: float
    reason: str | None


def equity_hard_stop_loss(
    *,
    equity_usdt: float,
    start_equity_usdt: float,
    max_drawdown_pct: float = 5.0,
) -> EquityHardStopDecision:
    start = max(0.0, float(start_equity_usdt or 0.0))
    equity = max(0.0, float(equity_usdt or 0.0))
    if start <= 0:
        return EquityHardStopDecision(False, equity, start, 0.0, "START_EQUITY_INVALID")
    dd = max(0.0, (start - equity) / start * 100.0)
    if dd >= float(max_drawdown_pct):
        return EquityHardStopDecision(False, round(equity, 8), round(start, 8), round(dd, 8), "EQUITY_HARD_STOP")
    return EquityHardStopDecision(True, round(equity, 8), round(start, 8), round(dd, 8), None)


__all__ = ["EquityHardStopDecision", "equity_hard_stop_loss"]
