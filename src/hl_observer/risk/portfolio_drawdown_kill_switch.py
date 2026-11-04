"""Portfolio drawdown kill switch for paper sessions."""

from __future__ import annotations

from dataclasses import dataclass
import math


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


def drawdown_kill_switch_receipt(*, peak_equity: float, current_equity: float, max_drawdown_pct: float = 5.0) -> dict[str, object]:
    """Return a validated paper-only drawdown kill-switch receipt."""
    values = (peak_equity, current_equity, max_drawdown_pct)
    if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in values):
        return {"status": "UNMEASURABLE", "reason": "EQUITY_OBSERVATION_INVALID"}
    if float(peak_equity) <= 0.0 or float(max_drawdown_pct) < 0.0:
        return {"status": "UNMEASURABLE", "reason": "KILL_SWITCH_PARAMETERS_INVALID"}
    result = evaluate_drawdown_kill_switch(
        peak_equity=float(peak_equity),
        current_equity=float(current_equity),
        max_drawdown_pct=float(max_drawdown_pct),
    )
    return {"status": "PROVEN", "triggered": result.triggered, "drawdown_pct": result.drawdown_pct,
            "reason": result.reason, "real_execution": False}


__all__ = ["DrawdownKillSwitch", "evaluate_drawdown_kill_switch", "drawdown_kill_switch_receipt"]
