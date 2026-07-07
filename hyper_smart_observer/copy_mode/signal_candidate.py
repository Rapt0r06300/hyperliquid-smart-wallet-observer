from __future__ import annotations

from datetime import datetime

from hyper_smart_observer.copy_mode.copy_models import (
    DeltaAction,
    EdgeInputs,
    LeaderDelta,
    NoTradeReason,
    SignalCandidate,
    SignalDecision,
    stable_hash,
    utc_now,
)
from hyper_smart_observer.copy_mode.edge import compute_edge_remaining_bps, liquidity_penalty_bps, price_deviation_penalty_bps, signal_freshness_factor


ENTRY_ACTIONS = {DeltaAction.OPEN_LONG, DeltaAction.OPEN_SHORT, DeltaAction.ADD, DeltaAction.INCREASE}


def build_signal_candidate(
    delta: LeaderDelta,
    *,
    leader_expected_edge_bps: float | None,
    current_mid: float | None,
    leader_score: float,
    observed_at: datetime | None = None,
    spread_bps: float = 2.0,
    slippage_bps: float = 5.0,
    fee_bps: float = 5.0,
    latency_ms: int = 500,
    liquidity_score: float = 1.0,
    min_edge_required_bps: float = 8.0,
    max_signal_age_ms: int = 300_000,
    min_liquidity_score: float = 0.50,
) -> SignalCandidate:
    now = observed_at or utc_now()
    age_ms = int((now - (delta.leader_fill_time or delta.observed_at)).total_seconds() * 1000)
    freshness = signal_freshness_factor(age_ms, stale_after_ms=max_signal_age_ms)
    reasons: list[str] = []
    # MID_MISSING / invalid mid => edge cannot be measured => NO_TRADE.
    if current_mid is None or current_mid <= 0:
        reasons.append(NoTradeReason.EDGE_UNMEASURABLE.value)
    if delta.action_type == DeltaAction.UNKNOWN:
        reasons.append(NoTradeReason.UNKNOWN_DELTA.value)
    if delta.action_type in {DeltaAction.REDUCE, DeltaAction.CLOSE_LONG, DeltaAction.CLOSE_SHORT}:
        reasons.append(NoTradeReason.REDUCE_OR_CLOSE_NOT_ENTRY.value)
    if age_ms > max_signal_age_ms:
        reasons.append(NoTradeReason.STALE_SIGNAL.value)
    if spread_bps > 50:
        reasons.append(NoTradeReason.SPREAD_TOO_WIDE.value)
    if slippage_bps > 30:
        reasons.append(NoTradeReason.SLIPPAGE_TOO_HIGH.value)
    if liquidity_score < min_liquidity_score:
        reasons.append(NoTradeReason.LIQUIDITY_TOO_LOW.value)
    adverse_price_penalty = price_deviation_penalty_bps(
        delta.action_type,
        delta.leader_reference_price,
        current_mid,
    )
    gross_edge_bps = None
    if leader_expected_edge_bps is not None:
        gross_edge_bps = (
            leader_expected_edge_bps
            * max(0.0, min(1.0, leader_score / 100.0))
            * freshness
        )
    adaptive_degradation_cap = 40.0
    if gross_edge_bps is not None:
        adaptive_degradation_cap = min(
            120.0,
            max(40.0, gross_edge_bps - min_edge_required_bps),
        )
    edge, degradation, edge_reasons = compute_edge_remaining_bps(
        EdgeInputs(
            leader_expected_edge_bps=leader_expected_edge_bps,
            leader_consistency_factor=max(0.0, min(1.0, leader_score / 100.0)),
            signal_freshness_factor=freshness,
            delay_cost_bps=max(0.0, age_ms / 60_000.0),
            spread_bps=spread_bps,
            slippage_bps=slippage_bps,
            fee_bps=fee_bps,
            liquidity_penalty_bps=liquidity_penalty_bps(
                liquidity_score,
                min_liquidity_score=min_liquidity_score,
            ),
            adverse_selection_penalty_bps=2.0 + adverse_price_penalty,
            crowding_penalty_bps=1.0,
            funding_penalty_bps=0.0,
        ),
        min_required_bps=min_edge_required_bps,
        max_copy_degradation_bps=adaptive_degradation_cap,
    )
    reasons.extend(reason for reason in edge_reasons if reason not in reasons)
    decision = SignalDecision.ACCEPT_PAPER if not reasons and delta.action_type in ENTRY_ACTIONS else SignalDecision.REJECT_NO_TRADE
    if decision == SignalDecision.ACCEPT_PAPER and (edge is None or edge < min_edge_required_bps):
        decision = SignalDecision.REJECT_NO_TRADE
        if NoTradeReason.EDGE_REMAINING_TOO_LOW.value not in reasons:
            reasons.append(NoTradeReason.EDGE_REMAINING_TOO_LOW.value)
    raw_hash = delta.raw_event_hash or stable_hash(f"{delta.leader_wallet}:{delta.coin}:{delta.action_type}:{delta.observed_at.isoformat()}")
    candidate_id = "sig:" + stable_hash(f"{raw_hash}:{current_mid}:{spread_bps}:{slippage_bps}")[:24]
    return SignalCandidate(
        candidate_id=candidate_id,
        leader_wallet=delta.leader_wallet,
        coin=delta.coin,
        action_type=delta.action_type,
        observed_at=now,
        leader_fill_time=delta.leader_fill_time,
        leader_reference_price=delta.leader_reference_price,
        current_mid=current_mid,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        fee_bps=fee_bps,
        latency_ms=latency_ms,
        liquidity_score=liquidity_score,
        leader_score=leader_score,
        signal_freshness_score=freshness,
        copy_degradation_bps=degradation,
        edge_remaining_bps=edge,
        paper_mode="PAPER_MOCK_USDC",
        decision=decision,
        refusal_reasons=reasons,
        raw_event_hash=raw_hash,
        source_snapshot_id=delta.source_snapshot_id,
        collection_run_id=delta.collection_run_id,
    )
