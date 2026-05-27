from __future__ import annotations

from hl_observer.hyperliquid.schemas import EdgeRemaining, EdgeRemainingInputs, SignalDecision


def compute_edge_remaining(
    inputs: EdgeRemainingInputs,
    *,
    min_edge_required_bps: float,
    max_liquidity_penalty_bps: float = 50.0,
    max_total_costs_bps: float = 100.0,
) -> EdgeRemaining:
    expected_edge_bps = (
        inputs.edge_leader_bps
        * inputs.consistency_factor
        * inputs.freshness_factor
    )
    costs_bps = (
        inputs.delay_cost_bps
        + inputs.spread_bps
        + inputs.slippage_bps
        + inputs.fees_bps
        + inputs.liquidity_penalty_bps
        + inputs.crowding_penalty_bps
        + inputs.adverse_selection_bps
        + inputs.funding_penalty_bps
    )
    edge_remaining_bps = expected_edge_bps - costs_bps

    reasons: list[str] = []
    decision = SignalDecision.PAPER_CANDIDATE

    # Rejection logic
    if inputs.edge_leader_bps <= 0:
        decision = SignalDecision.REJECT_EDGE_NEGATIVE
        reasons.append("missing_leader_edge")
    elif inputs.freshness_factor <= 0:
        decision = SignalDecision.REJECT_TOO_LATE
        reasons.append("signal_stale")
    elif inputs.observed_price <= 0:
        decision = SignalDecision.REJECT_INVALID_PRICE
        reasons.append("invalid_price")
    elif inputs.liquidity_penalty_bps > max_liquidity_penalty_bps:
        decision = SignalDecision.REJECT_TOO_ILLIQUID
        reasons.append("low_liquidity")
    elif edge_remaining_bps <= 0:
        decision = SignalDecision.REJECT_EDGE_NEGATIVE
        reasons.append("edge_remaining_bps <= 0")
    elif edge_remaining_bps < min_edge_required_bps:
        decision = SignalDecision.REJECT_EDGE_TOO_SMALL
        reasons.append("edge_remaining_bps below minimum")
    elif costs_bps > max_total_costs_bps:
        decision = SignalDecision.REJECT_COSTS_TOO_HIGH
        reasons.append("costs_too_high")

    if decision == SignalDecision.PAPER_CANDIDATE:
        reasons.append("edge_remaining_bps meets minimum")

    return EdgeRemaining(
        expected_edge_bps=expected_edge_bps,
        costs_bps=costs_bps,
        edge_remaining_bps=edge_remaining_bps,
        min_edge_required_bps=min_edge_required_bps,
        decision=decision,
        reasons=reasons,
    )
