"""V14 #180 — Decision cadence: slow-loop + cooldown + per-window budget for the paper loop.

mlmodelpoly runs a slow loop (~1 s) with a cooldown (~2 s) and a per-window budget (30 slices
/ 300 USD). This pure gate enforces "fewer, cleaner" entries: it refuses to decide too often,
too soon after the last decision, or beyond the window's count/notional budget. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class CadenceConfig:
    cooldown_s: float = 2.0
    window_s: float = 10.0
    max_decisions_per_window: int = 30
    max_notional_per_window_usd: float = 300.0


@dataclass(frozen=True, slots=True)
class CadenceVerdict:
    allowed: bool
    reason: str
    decisions_in_window: int
    notional_in_window_usd: float


def cadence_decision(
    *,
    now_s: float,
    last_decision_s: float | None,
    recent_decision_times_s: Sequence[float],
    window_notional_usd: float,
    intended_notional_usd: float,
    config: CadenceConfig | None = None,
) -> CadenceVerdict:
    """Allow a decision only if cooldown elapsed and window count/notional budget remains."""
    cfg = config or CadenceConfig()
    window_start = float(now_s) - cfg.window_s
    in_window = [t for t in recent_decision_times_s if t > window_start]
    n = len(in_window)
    if last_decision_s is not None and (float(now_s) - float(last_decision_s)) < cfg.cooldown_s:
        return CadenceVerdict(False, "COOLDOWN_ACTIVE", n, float(window_notional_usd))
    if n >= cfg.max_decisions_per_window:
        return CadenceVerdict(False, "WINDOW_COUNT_BUDGET_EXCEEDED", n, float(window_notional_usd))
    if float(window_notional_usd) + float(intended_notional_usd) > cfg.max_notional_per_window_usd:
        return CadenceVerdict(False, "WINDOW_NOTIONAL_BUDGET_EXCEEDED", n, float(window_notional_usd))
    return CadenceVerdict(True, "OK", n, float(window_notional_usd))


__all__ = ["CadenceConfig", "CadenceVerdict", "cadence_decision"]
