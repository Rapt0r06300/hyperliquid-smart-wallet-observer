from __future__ import annotations

from hl_observer.hyperliquid.schemas import EdgeRemaining, EdgeRemainingInputs, SignalDecision


def compute_edge_remaining(
    inputs: EdgeRemainingInputs,
    *,
    min_edge_required_bps: float,
) -> EdgeRemaining:
    expected_edge_bps = (
        inputs.leader_expected_move_bps
        + inputs.cluster_confirmation_bps
        + inputs.orderbook_confirmation_bps
        + inputs.regime_bonus_bps
    )
    costs_bps = (
        inputs.taker_fee_bps
        + inputs.spread_cost_bps
        + inputs.estimated_slippage_bps
        + inputs.latency_decay_bps
        + inputs.adverse_selection_bps
        + inputs.funding_expected_cost_bps
    )
    edge_remaining_bps = expected_edge_bps - costs_bps

    reasons: list[str] = []
    if edge_remaining_bps <= 0:
        decision = SignalDecision.REJECT_EDGE_NEGATIVE
        reasons.append("edge_remaining_bps <= 0")
    elif edge_remaining_bps < min_edge_required_bps:
        decision = SignalDecision.REJECT_EDGE_TOO_SMALL
        reasons.append("edge_remaining_bps below minimum")
    else:
        decision = SignalDecision.PAPER_CANDIDATE
        reasons.append("edge_remaining_bps meets minimum")

    return EdgeRemaining(
        expected_edge_bps=expected_edge_bps,
        costs_bps=costs_bps,
        edge_remaining_bps=edge_remaining_bps,
        min_edge_required_bps=min_edge_required_bps,
        decision=decision,
        reasons=reasons,
    )
