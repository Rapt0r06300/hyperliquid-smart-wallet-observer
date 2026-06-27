from __future__ import annotations

from hl_observer.following.follow_decision_engine import FollowDecisionResult, decide_follow_signal
from hl_observer.following.follow_signal_builder import FollowSignalDraft


def evaluate_position_follow(signal: FollowSignalDraft, *, wallet_action: str = "OPEN") -> FollowDecisionResult:
    return decide_follow_signal(
        signal_age_ms=signal.signal_age_ms,
        wallet_action=wallet_action,
        spread_bps=0.0,
        slippage_bps=0.0,
        wallet_score=100.0,
        pattern_score=100.0,
    )
