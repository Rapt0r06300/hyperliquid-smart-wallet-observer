from __future__ import annotations

from pydantic import BaseModel


class ExitPlan(BaseModel):
    id: str
    hard_stop_bps: float
    partial_take_profit_bps: float
    trailing_stop_bps: float
    breakeven_trigger_bps: float | None = None
    edge_decay_bps_limit: float = 5.0
    max_hold_ms: int
    leader_reduce_exit: bool = True
    kill_switch_exit: bool = True


def build_default_exit_plan(signal_id: str) -> ExitPlan:
    return ExitPlan(
        id=f"exit-{signal_id}",
        hard_stop_bps=25,
        partial_take_profit_bps=35,
        trailing_stop_bps=18,
        breakeven_trigger_bps=15,
        max_hold_ms=3_600_000,
    )
