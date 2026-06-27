from __future__ import annotations

from dataclasses import dataclass, field

from hyper_smart_observer.consensus.position_consensus import ConsensusSnapshot


@dataclass(slots=True)
class OpportunityCandidate:
    opportunity_id: str
    created_at_ms: int
    source: str
    coin: str
    action_type: str
    leader_wallets: list[str]
    wallet_count: int
    high_quality_wallet_count: int
    consensus_strength: float
    leader_reference_price: float | None
    current_mid: float | None
    signal_age_seconds: float
    estimated_delay_bps: float
    spread_bps: float
    slippage_bps: float
    fee_bps: float
    liquidity_score: float
    expected_edge_bps: float | None
    edge_remaining_bps: float | None
    simulation_expected_result: float | None
    confidence: float
    decision: str
    refusal_reasons: list[str] = field(default_factory=list)
    simulation_allowed: bool = False
    research_only_message: str = "Simulation sans argent uniquement. Ce n'est pas un ordre."


def evaluate_opportunity(
    snapshot: ConsensusSnapshot,
    *,
    created_at_ms: int,
    current_mid: float | None,
    expected_edge_bps: float | None,
    spread_bps: float = 2.0,
    slippage_bps: float = 5.0,
    fee_bps: float = 5.0,
    delay_bps: float = 2.0,
    min_edge_remaining_bps: float = 1.0,
    signal_age_seconds: float = 0.0,
    max_signal_age_seconds: float = 30.0,
    liquidity_score: float = 1.0,
) -> OpportunityCandidate:
    refusals: list[str] = []
    edge_remaining: float | None = None
    if snapshot.wallet_count < 2 or snapshot.high_quality_wallet_count < 1:
        refusals.append("INSUFFICIENT_CONSENSUS")
    if current_mid is None or current_mid <= 0:
        refusals.append("NO_CURRENT_MID")
    if signal_age_seconds > max_signal_age_seconds:
        refusals.append("STALE_SIGNAL")
    if liquidity_score < 0.25:
        refusals.append("LIQUIDITY_TOO_LOW")
    if expected_edge_bps is None:
        refusals.append("EDGE_UNMEASURABLE")
    else:
        edge_remaining = expected_edge_bps - delay_bps - spread_bps - slippage_bps - fee_bps
        if edge_remaining < min_edge_remaining_bps:
            refusals.append("EDGE_REMAINING_TOO_LOW")
    decision = "ACCEPT_FOR_SIMULATION_ONLY" if not refusals else "REJECT_NO_TRADE"
    confidence = min(1.0, snapshot.consensus_strength * max(0.0, liquidity_score))
    return OpportunityCandidate(
        opportunity_id=f"{created_at_ms}:{snapshot.coin}:{snapshot.direction}:{snapshot.action_type}",
        created_at_ms=created_at_ms,
        source="local_consensus",
        coin=snapshot.coin,
        action_type=snapshot.action_type,
        leader_wallets=snapshot.top_wallets,
        wallet_count=snapshot.wallet_count,
        high_quality_wallet_count=snapshot.high_quality_wallet_count,
        consensus_strength=snapshot.consensus_strength,
        leader_reference_price=current_mid,
        current_mid=current_mid,
        signal_age_seconds=signal_age_seconds,
        estimated_delay_bps=delay_bps,
        spread_bps=spread_bps,
        slippage_bps=slippage_bps,
        fee_bps=fee_bps,
        liquidity_score=liquidity_score,
        expected_edge_bps=expected_edge_bps,
        edge_remaining_bps=None if edge_remaining is None else round(edge_remaining, 6),
        simulation_expected_result=None if edge_remaining is None else round(edge_remaining / 10_000.0 * 50.0, 8),
        confidence=round(confidence, 6),
        decision=decision,
        refusal_reasons=refusals,
        simulation_allowed=decision == "ACCEPT_FOR_SIMULATION_ONLY",
    )
