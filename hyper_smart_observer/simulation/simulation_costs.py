from __future__ import annotations

from hyper_smart_observer.simulation.simulation_models import SimulationSide


def fee_for_notional(notional: float, fee_bps: float) -> float:
    if notional < 0:
        raise ValueError("notional must be non-negative")
    if fee_bps < 0:
        raise ValueError("fee_bps must be non-negative")
    return notional * fee_bps / 10_000.0


def apply_spread_and_slippage(price: float, side: SimulationSide, spread_bps: float, slippage_bps: float) -> float:
    if price <= 0:
        raise ValueError("price must be positive")
    if spread_bps < 0 or slippage_bps < 0:
        raise ValueError("spread/slippage must be non-negative")
    penalty = (spread_bps + slippage_bps) / 10_000.0
    if side == SimulationSide.LONG:
        return price * (1.0 + penalty)
    return price * (1.0 - penalty)

