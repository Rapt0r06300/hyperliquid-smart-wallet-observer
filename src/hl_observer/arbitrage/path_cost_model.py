"""Cost model for simulated arbitrage paths."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PathCost:
    legs: int
    total_fee_bps: float
    total_slippage_bps: float
    total_spread_bps: float
    total_cost_bps: float


def path_cost_bps(
    *,
    legs: int,
    fee_bps_per_leg: float = 4.5,
    slippage_bps_per_leg: float = 2.0,
    spread_bps_per_leg: float = 1.0,
) -> PathCost:
    n = max(1, int(legs))
    fee = n * max(0.0, float(fee_bps_per_leg))
    slip = n * max(0.0, float(slippage_bps_per_leg))
    spread = n * max(0.0, float(spread_bps_per_leg))
    return PathCost(n, round(fee, 8), round(slip, 8), round(spread, 8), round(fee + slip + spread, 8))


__all__ = ["PathCost", "path_cost_bps"]
