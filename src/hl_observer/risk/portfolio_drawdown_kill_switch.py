"""Portfolio drawdown kill switch for paper sessions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DrawdownKillSwitch:
    triggered: bool
    drawdown_pct: float
    reason: str


def evaluate_drawdown_kill_switch(*, peak_equity: float, current_equity: float, max_drawdown_pct: float = 5.0) -> DrawdownKillSwitch:
    peak = max(float(peak_equity), 1e-9)
    drawdown = max(0.0, (peak - float(current_equity)) / peak * 100.0)
    triggered = drawdown >= float(max_drawdown_pct)
    return DrawdownKillSwitch(triggered, round(drawdown, 8), "PORTFOLIO_DRAWDOWN_KILL_SWITCH" if triggered else "OK")


__all__ = ["DrawdownKillSwitch", "evaluate_drawdown_kill_switch"]
