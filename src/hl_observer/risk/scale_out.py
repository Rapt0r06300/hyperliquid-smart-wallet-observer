"""V15 #201 — Partial profit-taking (scale-out) + move-to-breakeven (paper exits)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


def _profit_bps(entry: float, current: float, side: str) -> float:
    if entry <= 0:
        return 0.0
    raw = (float(current) - float(entry)) / float(entry) * 10_000.0
    return raw if str(side).upper() in {"LONG", "BUY"} else -raw


@dataclass(frozen=True, slots=True)
class ScaleOutTranche:
    trigger_bps: float
    fraction: float
    take: bool


def scale_out_plan(
    *,
    entry_price: float,
    current_price: float,
    side: str,
    tranches: Sequence[tuple[float, float]],   # (trigger_bps, fraction)
) -> list[ScaleOutTranche]:
    """Mark which tranches are in-profit enough to take now."""
    p = _profit_bps(entry_price, current_price, side)
    return [ScaleOutTranche(float(t), float(f), p >= float(t)) for t, f in tranches]


def move_to_breakeven(
    *,
    entry_price: float,
    current_price: float,
    side: str,
    trigger_bps: float = 30.0,
) -> tuple[bool, float | None]:
    """Once profit >= trigger, move the stop to entry (breakeven). Returns (moved, stop)."""
    if _profit_bps(entry_price, current_price, side) >= float(trigger_bps):
        return True, float(entry_price)
    return False, None


def close_grid_fraction(profit_bps: float, *, levels=((14.0, 0.34), (58.0, 0.634))) -> float:
    """Fraction cumulee a fermer selon le profit atteint (passivbot close_grid_qty_pct)."""
    frac = 0.0
    for lvl_bps, f in levels:
        if profit_bps >= lvl_bps:
            frac = f
    return frac


def trailing_close_triggered(peak_profit_bps: float, current_profit_bps: float, *, threshold_bps: float = 349.0) -> bool:
    """Cloture trailing : rebrousse de plus de threshold depuis le pic de profit (passivbot)."""
    return peak_profit_bps > 0.0 and (peak_profit_bps - current_profit_bps) >= threshold_bps

__all__ = ["ScaleOutTranche", "scale_out_plan", "move_to_breakeven", "close_grid_fraction", "trailing_close_triggered"]
