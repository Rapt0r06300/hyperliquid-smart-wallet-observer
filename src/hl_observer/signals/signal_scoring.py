from __future__ import annotations

from hl_observer.hyperliquid.schemas import SignalCandidate, SignalDecision, SignalScore
from hl_observer.utils.math import clamp


def score_signal(signal: SignalCandidate) -> SignalScore:
    reasons: list[str] = []
    freshness = clamp(1.0 - signal.signal_age_ms / 3500.0, 0.0, 1.0) * 30.0
    edge = clamp(signal.edge_remaining_bps / 25.0, 0.0, 1.0) * 35.0
    liquidity = clamp(signal.orderbook_depth_usdc / 25000.0, 0.0, 1.0) * 20.0
    spread_penalty = clamp(signal.spread_bps / 10.0, 0.0, 1.0) * 10.0
    crowding_penalty = clamp(signal.crowding_score, 0.0, 1.0) * 10.0
    score = clamp(freshness + edge + liquidity - spread_penalty - crowding_penalty + 15.0, 0.0, 100.0)

    if signal.signal_age_ms > 3500:
        reasons.append("signal_too_late")
    if signal.edge_remaining_bps <= 0:
        reasons.append("edge_negative")
    if not signal.exit_plan_id:
        reasons.append("exit_plan_missing")

    decision = SignalDecision.PAPER_CANDIDATE if score >= 80 and not reasons else SignalDecision.OBSERVE_ONLY
    if "signal_too_late" in reasons:
        decision = SignalDecision.REJECT_TOO_LATE
    elif "edge_negative" in reasons:
        decision = SignalDecision.REJECT_EDGE_NEGATIVE
    elif "exit_plan_missing" in reasons:
        decision = SignalDecision.REJECT_EXIT_PLAN_WEAK

    return SignalScore(signal_id=signal.id, score=score, decision=decision, reasons=reasons)
