"""V12 edge net estimator with explicit unmeasurable states.

The older edge calculators handle arithmetic once all inputs exist. This module
adds the V12 contract around them: required data must be present, costs are
visible, and a missing market fact becomes NO_TRADE rather than a guessed value.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math


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


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    parsed = float(value)
    return parsed if math.isfinite(parsed) else None


def estimate_edge_net_v12(inputs: EdgeNetV12Inputs) -> EdgeNetV12Estimate:
    reasons: list[str] = []
    missing: list[str] = []
    leader_reference_price = _finite_number(inputs.leader_reference_price)
    current_mid = _finite_number(inputs.current_mid)
    leader_expected_edge = _finite_number(inputs.leader_expected_edge_bps)
    spread = _finite_number(inputs.spread_bps)
    slippage = _finite_number(inputs.slippage_bps)
    fee = _finite_number(inputs.fee_bps)
    if leader_reference_price is None or leader_reference_price <= 0:
        missing.append("leader_reference_price")
        reasons.append("EDGE_UNMEASURABLE")
    if current_mid is None or current_mid <= 0:
        missing.append("current_mid")
        reasons.append("MID_MISSING")
    if leader_expected_edge is None:
        missing.append("leader_expected_edge_bps")
        reasons.append("EDGE_UNMEASURABLE")
    elif leader_expected_edge < 0:
        reasons.append("EDGE_REMAINING_TOO_LOW")
    if spread is None or spread < 0:
        missing.append("spread_bps")
        reasons.append("SPREAD_TOO_WIDE")
    if slippage is None or slippage < 0:
        missing.append("slippage_bps")
        reasons.append("LIQUIDITY_TOO_LOW")
    if fee is None or fee < 0:
        missing.append("fee_bps")
        reasons.append("EDGE_UNMEASURABLE")
    threshold = _finite_number(inputs.min_edge_bps)
    max_copy_degradation = _finite_number(inputs.max_copy_degradation_bps)
    if threshold is None or threshold < 0 or max_copy_degradation is None or max_copy_degradation < 0:
        missing.append("edge_thresholds")
        reasons.append("EDGE_UNMEASURABLE")
    optional_costs = {
        "latency_penalty_bps": inputs.latency_penalty_bps,
        "copy_degradation_bps": inputs.copy_degradation_bps,
        "liquidity_penalty_bps": inputs.liquidity_penalty_bps,
        "volatility_penalty_bps": inputs.volatility_penalty_bps,
        "adverse_selection_penalty_bps": inputs.adverse_selection_penalty_bps,
        "crowding_penalty_bps": inputs.crowding_penalty_bps,
    }
    optional_values: dict[str, float] = {}
    for name, value in optional_costs.items():
        parsed = _finite_number(value)
        if parsed is None or parsed < 0:
            missing.append(name)
            reasons.append("EDGE_UNMEASURABLE")
        else:
            optional_values[name] = parsed
    funding = _finite_number(inputs.funding_estimate_bps)
    if inputs.funding_estimate_bps is not None and (funding is None or funding < 0):
        missing.append("funding_estimate_bps")
        reasons.append("EDGE_UNMEASURABLE")
    elif inputs.funding_estimate_bps is None:
        reasons.append("FUNDING_UNKNOWN")

    if missing:
        return EdgeNetV12Estimate(
            measurable=False,
            accepted=False,
            gross_edge_bps=None,
            total_cost_bps=None,
            net_edge_bps=None,
            threshold_bps=threshold if threshold is not None else 0.0,
            reason_codes=tuple(dict.fromkeys(reasons)),
            cost_breakdown_bps={},
        )

    costs = {
        "spread_bps": spread,
        "slippage_bps": slippage,
        "fee_bps": fee,
        **optional_values,
        "funding_estimate_bps": funding if funding is not None else 0.0,
    }
    total_cost = sum(costs.values())
    net = leader_expected_edge - total_cost

    if costs["copy_degradation_bps"] > max_copy_degradation:
        reasons.append("COPY_DEGRADATION_TOO_HIGH")
    if net < threshold:
        reasons.append("EDGE_REMAINING_TOO_LOW")
    if net <= 0:
        reasons.append("EDGE_UNMEASURABLE" if inputs.leader_expected_edge_bps is None else "EDGE_REMAINING_TOO_LOW")

    unique = tuple(dict.fromkeys(reasons))
    return EdgeNetV12Estimate(
        measurable=True,
        accepted=not unique,
        gross_edge_bps=round(leader_expected_edge, 8),
        total_cost_bps=round(total_cost, 8),
        net_edge_bps=round(net, 8),
        threshold_bps=threshold,
        reason_codes=unique,
        cost_breakdown_bps={k: round(v, 8) for k, v in costs.items()},
    )


__all__ = ["EdgeNetV12Estimate", "EdgeNetV12Inputs", "estimate_edge_net_v12"]
