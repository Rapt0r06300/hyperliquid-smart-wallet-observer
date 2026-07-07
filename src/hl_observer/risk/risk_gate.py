"""R11 — Gate de risque unifie : halts perte + drawdown kill + VaR + loss-streak.

Compose en un seul verdict les gardes de risque (gajesh drawdown kill, MrFadiAi
halts jour/mois, CloddsBot VaR). Pur : consomme un etat deja calcule, rend
(ok, reasons). Bloque les NOUVELLES entrees ; ne touche jamais a un ordre reel.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class RiskGateState:
    daily_loss_pct: float = 0.0          # perte du jour (valeur positive = perte)
    monthly_loss_pct: float = 0.0
    drawdown_pct: float = 0.0            # depuis le pic d'equity
    loss_streak: int = 0                 # pertes consecutives
    var_bps: float | None = None         # VaR estimee (bps, positive = risque)


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


def evaluate_risk_gate(state: RiskGateState, config: RiskGateConfig | None = None) -> RiskGateVerdict:
    cfg = config or RiskGateConfig()
    reasons: list[str] = []
    if state.daily_loss_pct >= cfg.max_daily_loss_pct:
        reasons.append(f"DAILY_LOSS_HALT>={cfg.max_daily_loss_pct}")
    if state.monthly_loss_pct >= cfg.max_monthly_loss_pct:
        reasons.append(f"MONTHLY_LOSS_HALT>={cfg.max_monthly_loss_pct}")
    if state.drawdown_pct >= cfg.max_drawdown_pct:
        reasons.append(f"DRAWDOWN_KILL_SWITCH>={cfg.max_drawdown_pct}")
    if state.loss_streak >= cfg.max_loss_streak:
        reasons.append(f"LOSS_STREAK_HALT>={cfg.max_loss_streak}")
    if cfg.max_var_bps is not None and state.var_bps is not None and state.var_bps >= cfg.max_var_bps:
        reasons.append(f"VAR_BUDGET_EXCEEDED>={cfg.max_var_bps}")
    return RiskGateVerdict(ok=(len(reasons) == 0), reasons=tuple(reasons))


__all__ = ["RiskGateState", "RiskGateConfig", "RiskGateVerdict", "evaluate_risk_gate"]
