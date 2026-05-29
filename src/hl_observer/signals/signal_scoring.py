from __future__ import annotations

from hl_observer.hyperliquid.schemas import SignalCandidate, SignalDecision, SignalScore
from hl_observer.utils.math import clamp


def score_signal(signal: SignalCandidate) -> SignalScore:
    """
    Advanced signal scoring integrating edge remaining and gain assurance.
    """
    reasons: list[str] = []

    # 35% weight on Gain Assurance (the core probability of success)
    gain_assurance_component = signal.gain_assurance_score * 0.35

    # 25% weight on Residual Edge
    edge_component = clamp(signal.edge_remaining_bps / 30.0, 0.0, 1.0) * 25.0

    # 20% weight on Wallet Reputation
    wallet_component = clamp(signal.wallet_score / 100.0, 0.0, 1.0) * 20.0

    # 10% weight on Freshness (already in gain assurance, but critical to double-check)
    freshness_component = clamp(1.0 - signal.signal_age_ms / 5000.0, 0.0, 1.0) * 10.0

    # 10% weight on Orderbook Quality
    depth_score = clamp(signal.orderbook_depth_usdc / 20000.0, 0.0, 1.0) * 10.0

    base_score = (
        gain_assurance_component +
        edge_component +
        wallet_component +
        freshness_component +
        depth_score
    )

    # Apply severe penalties
    spread_penalty = clamp(signal.spread_bps / 8.0, 0.0, 1.0) * 15.0
    crowding_penalty = clamp(signal.crowding_score, 0.0, 1.0) * 10.0

    score = clamp(base_score - spread_penalty - crowding_penalty, 0.0, 100.0)

    # Rejection logic
    if signal.signal_age_ms > 3500:
        reasons.append("signal_too_late")
    if signal.edge_remaining_bps <= 0:
        reasons.append("edge_negative")
    if signal.gain_assurance_score < 40.0:
        reasons.append("gain_assurance_too_low")
    if not signal.exit_plan_id:
        reasons.append("exit_plan_missing")

    decision = SignalDecision.PAPER_CANDIDATE if score >= 75 and not reasons else SignalDecision.OBSERVE_ONLY

    if "signal_too_late" in reasons:
        decision = SignalDecision.REJECT_TOO_LATE
    elif "edge_negative" in reasons:
        decision = SignalDecision.REJECT_EDGE_NEGATIVE
    elif "gain_assurance_too_low" in reasons:
        decision = SignalDecision.REJECT_EDGE_TOO_WEAK
    elif "exit_plan_missing" in reasons:
        decision = SignalDecision.REJECT_EXIT_PLAN_WEAK

    return SignalScore(signal_id=signal.id, score=score, decision=decision, reasons=reasons)
