from __future__ import annotations

from enum import StrEnum
from pydantic import BaseModel


class ExitReason(StrEnum):
    HARD_STOP = "HARD_STOP"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"
    TIME_STOP = "TIME_STOP"
    LEADER_REDUCE = "LEADER_REDUCE"
    LEADER_CLOSE = "LEADER_CLOSE"
    KILL_SWITCH = "KILL_SWITCH"


class ExitPlan(BaseModel):
    id: str
    hard_stop_bps: float
    partial_take_profit_bps: float
    trailing_stop_bps: float
    max_hold_ms: int
    leader_reduce_exit: bool = True
    kill_switch_exit: bool = True


def build_default_exit_plan(signal_id: str) -> ExitPlan:
    return ExitPlan(
        id=f"exit-{signal_id}",
        hard_stop_bps=25.0,
        partial_take_profit_bps=35.0,
        trailing_stop_bps=18.0,
        max_hold_ms=3_600_000,
    )


class ExitDecision(BaseModel):
    should_exit: bool
    reason: ExitReason | None = None
    exit_pct: float = 0.0


class AdvancedExitEngine:
    """Multi-stage exit logic for paper simulations."""

    def evaluate_exit(
        self,
        exit_plan: ExitPlan,
        entry_price: float,
        current_price: float,
        side: str,
        entry_time_ms: int,
        current_time_ms: int,
        highest_price: float | None = None,
    ) -> ExitDecision:
        pnl_bps = (
            (current_price - entry_price) / entry_price * 10_000
            if side.upper() == "LONG"
            else (entry_price - current_price) / entry_price * 10_000
        )

        # 1. Hard Stop
        if pnl_bps <= -exit_plan.hard_stop_bps:
            return ExitDecision(should_exit=True, reason=ExitReason.HARD_STOP, exit_pct=1.0)

        # 2. Take Profit
        if pnl_bps >= exit_plan.partial_take_profit_bps:
            return ExitDecision(should_exit=True, reason=ExitReason.TAKE_PROFIT, exit_pct=0.5)

        # 3. Trailing Stop
        if highest_price:
            peak_pnl_bps = (
                (highest_price - entry_price) / entry_price * 10_000
                if side.upper() == "LONG"
                else (entry_price - highest_price) / entry_price * 10_000
            )
            # If we were in profit > 10 bps, but dropped by trailing_stop_bps
            if peak_pnl_bps > 10 and (peak_pnl_bps - pnl_bps) >= exit_plan.trailing_stop_bps:
                return ExitDecision(should_exit=True, reason=ExitReason.TRAILING_STOP, exit_pct=1.0)

        # 4. Time Stop
        if (current_time_ms - entry_time_ms) >= exit_plan.max_hold_ms:
            return ExitDecision(should_exit=True, reason=ExitReason.TIME_STOP, exit_pct=1.0)

        return ExitDecision(should_exit=False)
