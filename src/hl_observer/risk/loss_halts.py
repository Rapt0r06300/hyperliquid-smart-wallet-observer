"""Multi-layer loss halts (S7 — V9, MrFadiAi A1).

Layers (deny-by-default, most severe wins on pause length):
  * daily loss   >= 5%   -> pause 60 min
  * monthly loss >= 15%  -> pause 30 days
  * drawdown from peak >= 25% -> pause 7 days
  * trailing give-back >= configured -> pause 60 min

All inputs are *paper* PnL percentages. Losses are passed as signed PnL%
(negative = loss); the engine converts to loss magnitude internally.

SAFETY: a halt only blocks new *paper* entries. Nothing real is ever placed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

_DAY = 86_400


@dataclass(frozen=True, slots=True)
class LossHaltConfig:
    daily_loss_halt_pct: float = 5.0
    daily_pause_sec: int = 3_600
    monthly_loss_halt_pct: float = 15.0
    monthly_pause_sec: int = 30 * _DAY
    drawdown_halt_pct: float = 25.0
    drawdown_pause_sec: int = 7 * _DAY
    trailing_giveback_pct: float | None = None
    trailing_pause_sec: int = 3_600


@dataclass(frozen=True, slots=True)
class LossHaltState:
    daily_pnl_pct: float = 0.0
    monthly_pnl_pct: float = 0.0
    peak_equity: float = 0.0
    current_equity: float = 0.0
    session_peak_equity: float | None = None


@dataclass(frozen=True, slots=True)
class HaltDecision:
    halted: bool
    pause_sec: int
    triggers: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not self.halted


def _loss_pct(pnl_pct: float) -> float:
    return max(0.0, -pnl_pct)


def drawdown_from_peak_pct(peak_equity: float, current_equity: float) -> float:
    if peak_equity <= 0:
        return 0.0
    return max(0.0, (peak_equity - current_equity) / peak_equity * 100.0)


def evaluate_loss_halts(state: LossHaltState, config: LossHaltConfig | None = None) -> HaltDecision:
    cfg = config or LossHaltConfig()
    triggers: list[tuple[str, int]] = []

    if _loss_pct(state.daily_pnl_pct) >= cfg.daily_loss_halt_pct:
        triggers.append(("DAILY_LOSS_HALT", cfg.daily_pause_sec))

    if _loss_pct(state.monthly_pnl_pct) >= cfg.monthly_loss_halt_pct:
        triggers.append(("MONTHLY_LOSS_HALT", cfg.monthly_pause_sec))

    dd = drawdown_from_peak_pct(state.peak_equity, state.current_equity)
    if dd >= cfg.drawdown_halt_pct:
        triggers.append(("DRAWDOWN_HALT", cfg.drawdown_pause_sec))

    if cfg.trailing_giveback_pct is not None and state.session_peak_equity:
        giveback = drawdown_from_peak_pct(state.session_peak_equity, state.current_equity)
        if giveback >= cfg.trailing_giveback_pct:
            triggers.append(("TRAILING_GIVEBACK_HALT", cfg.trailing_pause_sec))

    if not triggers:
        return HaltDecision(halted=False, pause_sec=0, triggers=())
    pause = max(sec for _, sec in triggers)
    return HaltDecision(halted=True, pause_sec=pause, triggers=tuple(name for name, _ in triggers))
