"""F9/F10 — Budget de trades : plafonds de positions concurrentes, trades/jour, et
objectif d'equity journalier (verrouiller les gains). Anti-overtrading. Pur.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TradeBudget:
    max_concurrent: int = 12
    max_trades_per_day: int = 40
    daily_profit_target_pct: float = 0.0   # 0 = pas de verrou


def can_open(budget: TradeBudget, *, open_positions: int, trades_today: int,
            day_pnl_pct: float) -> tuple[bool, str]:
    if open_positions >= budget.max_concurrent:
        return False, f"MAX_CONCURRENT_REACHED({budget.max_concurrent})"
    if trades_today >= budget.max_trades_per_day:
        return False, f"MAX_TRADES_PER_DAY_REACHED({budget.max_trades_per_day})"
    if budget.daily_profit_target_pct > 0.0 and day_pnl_pct >= budget.daily_profit_target_pct:
        return False, f"DAILY_TARGET_LOCKED(+{budget.daily_profit_target_pct}%)"
    return True, "OK"


__all__ = ["TradeBudget", "can_open"]
