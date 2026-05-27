from hl_observer.following.follow_decision_engine import FollowDecisionKind, decide_follow_signal


def test_follow_signal_rejects_stale_signal():
    decision = decide_follow_signal(
        signal_age_ms=10_000,
        wallet_action="OPEN",
        spread_bps=1,
        slippage_bps=1,
        wallet_score=90,
        pattern_score=90,
    )

    assert decision.decision == FollowDecisionKind.REJECT_TOO_LATE


def test_follow_signal_rejects_wallet_closing():
    decision = decide_follow_signal(
        signal_age_ms=1,
        wallet_action="CLOSE",
        spread_bps=1,
        slippage_bps=1,
        wallet_score=90,
        pattern_score=90,
    )

    assert decision.decision == FollowDecisionKind.REJECT_WALLET_CLOSING


def test_follow_signal_rejects_too_wide_spread():
    decision = decide_follow_signal(
        signal_age_ms=1,
        wallet_action="OPEN",
        spread_bps=99,
        slippage_bps=1,
        wallet_score=90,
        pattern_score=90,
    )

    assert decision.decision == FollowDecisionKind.REJECT_SPREAD_TOO_WIDE
