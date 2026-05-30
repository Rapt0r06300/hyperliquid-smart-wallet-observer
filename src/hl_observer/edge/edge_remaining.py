from __future__ import annotations

from hl_observer.hyperliquid.schemas import EdgeRemaining, EdgeRemainingInputs, SignalDecision


def compute_edge_remaining(
    inputs: EdgeRemainingInputs,
    *,
    min_edge_required_bps: float,
    max_liquidity_penalty_bps: float = 50.0,
    max_total_costs_bps: float = 100.0,
) -> EdgeRemaining:
    """
    The Ultimate Professional Edge Calculation Formula.

    Formula: edge_remaining = (leader_edge * consistency * freshness) - costs
    """
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

    # Ultra-detailed Rejection Diagnostics
    if inputs.edge_leader_bps <= 0:
        decision = SignalDecision.REJECT_EDGE_NEGATIVE
        reasons.append(f"leader_edge_non_positive: {inputs.edge_leader_bps:.1f}bps")
    elif inputs.freshness_factor <= 0.1:
        decision = SignalDecision.REJECT_STALE_SIGNAL
        reasons.append(f"alpha_evaporated: freshness {inputs.freshness_factor:.2f}")
    elif inputs.observed_price <= 0:
        decision = SignalDecision.REJECT_INVALID_PRICE
        reasons.append(f"invalid_execution_price: {inputs.observed_price:.4f}")
    elif inputs.liquidity_penalty_bps > max_liquidity_penalty_bps:
        decision = SignalDecision.REJECT_TOO_ILLIQUID
        reasons.append(f"liquidity_risk: penalty {inputs.liquidity_penalty_bps:.1f}bps > limit {max_liquidity_penalty_bps:.1f}bps")
    elif edge_remaining_bps <= 0:
        decision = SignalDecision.REJECT_EDGE_NEGATIVE
        reasons.append(f"edge_exhausted_by_costs: {edge_remaining_bps:.1f}bps remaining")
    elif edge_remaining_bps < min_edge_required_bps:
        decision = SignalDecision.REJECT_EDGE_TOO_SMALL
        reasons.append(f"edge_insufficient: {edge_remaining_bps:.1f}bps < min {min_edge_required_bps:.1f}bps")
    elif costs_bps > max_total_costs_bps:
        decision = SignalDecision.REJECT_COSTS_TOO_HIGH
        reasons.append(f"prohibitive_costs: {costs_bps:.1f}bps > budget {max_total_costs_bps:.1f}bps")

    if decision == SignalDecision.PAPER_CANDIDATE:
        reasons.append(f"high_conviction_edge: {edge_remaining_bps:.1f}bps net")

    return EdgeRemaining(
        expected_edge_bps=expected_edge_bps,
        costs_bps=costs_bps,
        edge_remaining_bps=edge_remaining_bps,
        min_edge_required_bps=min_edge_required_bps,
        decision=decision,
        reasons=reasons,
    )
