"""V12 edge net estimator with explicit unmeasurable states.

The older edge calculators handle arithmetic once all inputs exist. This module
adds the V12 contract around them: required data must be present, costs are
visible, and a missing market fact becomes NO_TRADE rather than a guessed value.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class EdgeNetV12Inputs:
    leader_reference_price: float | None
    current_mid: float | None
    leader_expected_edge_bps: float | None
    spread_bps: float | None
    slippage_bps: float | None
    fee_bps: float | None
    latency_penalty_bps: float = 0.0
    copy_degradation_bps: float = 0.0
    liquidity_penalty_bps: float = 0.0
    volatility_penalty_bps: float = 0.0
    adverse_selection_penalty_bps: float = 0.0
    crowding_penalty_bps: float = 0.0
    funding_estimate_bps: float | None = None
    min_edge_bps: float = 30.0
    max_copy_degradation_bps: float = 40.0


@dataclass(frozen=True, slots=True)
class EdgeNetV12Estimate:
    measurable: bool
    accepted: bool
    gross_edge_bps: float | None
    total_cost_bps: float | None
    net_edge_bps: float | None
    threshold_bps: float
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    cost_breakdown_bps: dict[str, float] = field(default_factory=dict)


def estimate_edge_net_v12(inputs: EdgeNetV12Inputs) -> EdgeNetV12Estimate:
    reasons: list[str] = []
    missing: list[str] = []
    if inputs.leader_reference_price is None or inputs.leader_reference_price <= 0:
        missing.append("leader_reference_price")
        reasons.append("EDGE_UNMEASURABLE")
    if inputs.current_mid is None or inputs.current_mid <= 0:
        missing.append("current_mid")
        reasons.append("MID_MISSING")
    if inputs.leader_expected_edge_bps is None:
        missing.append("leader_expected_edge_bps")
        reasons.append("EDGE_UNMEASURABLE")
    if inputs.spread_bps is None:
        missing.append("spread_bps")
        reasons.append("SPREAD_TOO_WIDE")
    if inputs.slippage_bps is None:
        missing.append("slippage_bps")
        reasons.append("LIQUIDITY_TOO_LOW")
    if inputs.fee_bps is None:
        missing.append("fee_bps")
        reasons.append("EDGE_UNMEASURABLE")
    if inputs.funding_estimate_bps is None:
        reasons.append("FUNDING_UNKNOWN")

    if missing:
        return EdgeNetV12Estimate(
            measurable=False,
            accepted=False,
            gross_edge_bps=None,
            total_cost_bps=None,
            net_edge_bps=None,
            threshold_bps=inputs.min_edge_bps,
            reason_codes=tuple(dict.fromkeys(reasons)),
            cost_breakdown_bps={},
        )

    costs = {
        "spread_bps": max(0.0, float(inputs.spread_bps or 0.0)),
        "slippage_bps": max(0.0, float(inputs.slippage_bps or 0.0)),
        "fee_bps": max(0.0, float(inputs.fee_bps or 0.0)),
        "latency_penalty_bps": max(0.0, float(inputs.latency_penalty_bps)),
        "copy_degradation_bps": max(0.0, float(inputs.copy_degradation_bps)),
        "liquidity_penalty_bps": max(0.0, float(inputs.liquidity_penalty_bps)),
        "volatility_penalty_bps": max(0.0, float(inputs.volatility_penalty_bps)),
        "adverse_selection_penalty_bps": max(0.0, float(inputs.adverse_selection_penalty_bps)),
        "crowding_penalty_bps": max(0.0, float(inputs.crowding_penalty_bps)),
        "funding_estimate_bps": max(0.0, float(inputs.funding_estimate_bps or 0.0)),
    }
    total_cost = sum(costs.values())
    net = float(inputs.leader_expected_edge_bps or 0.0) - total_cost

    if costs["copy_degradation_bps"] > inputs.max_copy_degradation_bps:
        reasons.append("COPY_DEGRADATION_TOO_HIGH")
    if net < inputs.min_edge_bps:
        reasons.append("EDGE_REMAINING_TOO_LOW")
    if net <= 0:
        reasons.append("EDGE_UNMEASURABLE" if inputs.leader_expected_edge_bps is None else "EDGE_REMAINING_TOO_LOW")

    unique = tuple(dict.fromkeys(reasons))
    return EdgeNetV12Estimate(
        measurable=True,
        accepted=not unique,
        gross_edge_bps=round(float(inputs.leader_expected_edge_bps or 0.0), 8),
        total_cost_bps=round(total_cost, 8),
        net_edge_bps=round(net, 8),
        threshold_bps=inputs.min_edge_bps,
        reason_codes=unique,
        cost_breakdown_bps={k: round(v, 8) for k, v in costs.items()},
    )


__all__ = ["EdgeNetV12Estimate", "EdgeNetV12Inputs", "estimate_edge_net_v12"]
