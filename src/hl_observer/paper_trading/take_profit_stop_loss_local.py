"""Local TP/SL checks for paper simulation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TpSlDecision:
    action: str
    reason: str
    pnl_bps: float


def evaluate_take_profit_stop_loss(*, side: str, entry_price: float, current_price: float, take_profit_bps: float, stop_loss_bps: float) -> TpSlDecision:
    side_u = str(side).upper()
    raw = (float(current_price) - float(entry_price)) / max(float(entry_price), 1e-9) * 10_000.0
    pnl_bps = raw if side_u == "LONG" else -raw
    if pnl_bps >= float(take_profit_bps):
        return TpSlDecision(action="CLOSE", reason="TAKE_PROFIT", pnl_bps=round(pnl_bps, 8))
    if pnl_bps <= -abs(float(stop_loss_bps)):
        return TpSlDecision(action="CLOSE", reason="STOP_LOSS", pnl_bps=round(pnl_bps, 8))
    return TpSlDecision(action="HOLD", reason="NO_EXIT", pnl_bps=round(pnl_bps, 8))


__all__ = ["TpSlDecision", "evaluate_take_profit_stop_loss"]
