"""R11 — Gate de risque unifie : halts perte + drawdown kill + VaR + loss-streak.

Pure, paper-only and fail-closed: incomplete or non-finite risk evidence blocks
new entries rather than silently bypassing a configured limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math


@dataclass(frozen=True, slots=True)
class RiskGateState:
    daily_loss_pct: float = 0.0
    monthly_loss_pct: float = 0.0
    drawdown_pct: float = 0.0
    loss_streak: int = 0
    var_bps: float | None = None


@dataclass(frozen=True, slots=True)
class RiskGateConfig:
    max_daily_loss_pct: float = 5.0
    max_monthly_loss_pct: float = 15.0
    max_drawdown_pct: float = 20.0
    max_loss_streak: int = 5
    max_var_bps: float | None = None


@dataclass(frozen=True, slots=True)
class RiskGateVerdict:
    ok: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


def _finite_nonnegative(value: object) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) >= 0.0
    except (TypeError, ValueError):
        return False


def evaluate_risk_gate(state: RiskGateState, config: RiskGateConfig | None = None) -> RiskGateVerdict:
    cfg = config or RiskGateConfig()
    reasons: list[str] = []

    limits = (
        ("DAILY_LOSS", state.daily_loss_pct, cfg.max_daily_loss_pct),
        ("MONTHLY_LOSS", state.monthly_loss_pct, cfg.max_monthly_loss_pct),
        ("DRAWDOWN", state.drawdown_pct, cfg.max_drawdown_pct),
    )
    for label, observed, limit in limits:
        if not _finite_nonnegative(limit):
            reasons.append(f"{label}_LIMIT_INVALID")
        elif not _finite_nonnegative(observed):
            reasons.append(f"{label}_UNMEASURED")
        elif float(observed) >= float(limit):
            suffix = "KILL_SWITCH" if label == "DRAWDOWN" else "HALT"
            reasons.append(f"{label}_{suffix}>={limit}")

    if not isinstance(cfg.max_loss_streak, int) or isinstance(cfg.max_loss_streak, bool) or cfg.max_loss_streak < 0:
        reasons.append("LOSS_STREAK_LIMIT_INVALID")
    elif not isinstance(state.loss_streak, int) or isinstance(state.loss_streak, bool) or state.loss_streak < 0:
        reasons.append("LOSS_STREAK_UNMEASURED")
    elif state.loss_streak >= cfg.max_loss_streak:
        reasons.append(f"LOSS_STREAK_HALT>={cfg.max_loss_streak}")

    if cfg.max_var_bps is not None:
        if not _finite_nonnegative(cfg.max_var_bps):
            reasons.append("VAR_LIMIT_INVALID")
        elif state.var_bps is None:
            reasons.append("VAR_UNMEASURED")
        elif not _finite_nonnegative(state.var_bps):
            reasons.append("VAR_UNMEASURED")
        elif float(state.var_bps) >= float(cfg.max_var_bps):
            reasons.append(f"VAR_BUDGET_EXCEEDED>={cfg.max_var_bps}")

    return RiskGateVerdict(ok=not reasons, reasons=tuple(dict.fromkeys(reasons)))


__all__ = ["RiskGateState", "RiskGateConfig", "RiskGateVerdict", "evaluate_risk_gate"]
