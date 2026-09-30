from __future__ import annotations

from hl_observer.hyperliquid.schemas import SignalCandidate, SignalDecision, SignalScore
from hl_observer.utils.math import clamp

# Fenêtre de fraîcheur adaptée au mode polling (60-120s par cycle).
# 10 minutes = 600 000 ms : un signal de 0 ms a fraîcheur=1.0,
# un signal de 10 min a fraîcheur=0.0.  Le risk engine contrôle
# indépendamment la limite dure via max_signal_age_ms.
_FRESHNESS_WINDOW_MS: float = 600_000.0


def score_signal(signal: SignalCandidate) -> SignalScore:
    reasons: list[str] = []

    # Fraîcheur : décroissance linéaire sur 10 min (polling-compatible).
    freshness = clamp(1.0 - signal.signal_age_ms / _FRESHNESS_WINDOW_MS, 0.0, 1.0) * 25.0

    # Edge restant (principal facteur de qualité).
    edge = clamp(signal.edge_remaining_bps / 20.0, 0.0, 1.0) * 40.0

    # Liquidité disponible.
    liquidity = clamp(signal.orderbook_depth_usdc / 25_000.0, 0.0, 1.0) * 20.0

    # Pénalités coûts.
    spread_penalty = clamp(signal.estimated_spread_bps / 10.0, 0.0, 1.0) * 8.0
    crowding_penalty = clamp(signal.crowding_score, 0.0, 1.0) * 7.0

    score = clamp(freshness + edge + liquidity - spread_penalty - crowding_penalty + 10.0, 0.0, 100.0)

    if signal.edge_remaining_bps <= 0:
        reasons.append("edge_negative")
    if not signal.exit_plan_id:
        reasons.append("exit_plan_missing")

    # Note : plus de REJECT_TOO_LATE ici — c'est le risk engine qui
    # gère la limite dure (max_signal_age_ms configurable).
    if reasons:
        if "edge_negative" in reasons:
            decision = SignalDecision.REJECT_EDGE_NEGATIVE
        elif "exit_plan_missing" in reasons:
            decision = SignalDecision.REJECT_EXIT_PLAN_WEAK
        else:
            decision = SignalDecision.OBSERVE_ONLY
    else:
        decision = SignalDecision.PAPER_CANDIDATE if score >= 50.0 else SignalDecision.OBSERVE_ONLY

    return SignalScore(signal_id=signal.id, score=score, decision=decision, reasons=reasons)
