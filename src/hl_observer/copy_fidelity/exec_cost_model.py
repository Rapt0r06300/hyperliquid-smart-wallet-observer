"""V13 #150 — Deep execution cost model (paper): fees + maker rebate, slippage, passive
queue position, latency, L2 behavior → HONEST net edge after costs.

A trade is only worth taking if its gross edge survives ALL realistic costs. Pure / no order.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExecCosts:
    fee_bps: float
    spread_cost_bps: float
    slippage_bps: float
    latency_bps: float
    maker_rebate_bps: float        # >0 = credit (reduces cost)
    total_cost_bps: float


def queue_fill_probability(queue_ahead_usd: float, incoming_volume_usd: float) -> float:
    """Chance a passive (maker) order fills given the USD queued ahead vs incoming flow."""
    q = max(0.0, float(queue_ahead_usd))
    v = max(0.0, float(incoming_volume_usd))
    if v <= 0.0:
        return 0.0
    return max(0.0, min(1.0, (v - q) / v)) if v > q else 0.0


def model_exec_costs(
    *,
    fee_bps: float = 4.5,
    half_spread_bps: float = 0.0,
    slippage_bps: float = 0.0,
    latency_bps: float = 0.0,
    is_maker: bool = False,
    maker_rebate_bps: float = 0.5,
) -> ExecCosts:
    rebate = float(maker_rebate_bps) if is_maker else 0.0
    # a maker order does not pay the half-spread (it provides liquidity)
    spread_cost = 0.0 if is_maker else max(0.0, float(half_spread_bps))
    total = max(0.0, float(fee_bps)) + spread_cost + max(0.0, float(slippage_bps)) + max(0.0, float(latency_bps)) - rebate
    return ExecCosts(
        fee_bps=round(float(fee_bps), 4), spread_cost_bps=round(spread_cost, 4),
        slippage_bps=round(float(slippage_bps), 4), latency_bps=round(float(latency_bps), 4),
        maker_rebate_bps=round(rebate, 4), total_cost_bps=round(total, 4),
    )


def net_edge_after_costs(*, gross_edge_bps: float, costs: ExecCosts) -> float:
    return round(float(gross_edge_bps) - costs.total_cost_bps, 4)


__all__ = ["ExecCosts", "queue_fill_probability", "model_exec_costs", "net_edge_after_costs"]
