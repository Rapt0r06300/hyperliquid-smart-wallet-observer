from __future__ import annotations


def total_cost_bps(fee_bps: float, spread_bps: float, slippage_bps: float, latency_bps: float) -> float:
    return fee_bps + spread_bps + slippage_bps + latency_bps
