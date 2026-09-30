from hl_observer.hyperliquid.schemas import SignalCandidate, SignalDecision
from hl_observer.signals.signal_scoring import score_signal


def test_signal_decision_is_explicit():
    signal = SignalCandidate(
        id="s1",
        source_wallet="0xabc",
        coin="BTC",
        side="long",
        signal_type="open",
        observed_price=100,
        timestamp_ms=1,
        signal_age_ms=100,
        edge_remaining_bps=20,
        orderbook_depth_usdc=20000,
        exit_plan_id="exit-1",
    )

    score = score_signal(signal)

    assert isinstance(score.decision, SignalDecision)


def test_rejected_signal_has_reason():
    signal = SignalCandidate(
        id="s2",
        source_wallet="0xabc",
        coin="BTC",
        side="long",
        signal_type="open",
        observed_price=100,
        timestamp_ms=1,
        signal_age_ms=100,
        edge_remaining_bps=-1,
        orderbook_depth_usdc=20000,
        exit_plan_id="exit-1",
    )

    score = score_signal(signal)

    assert score.decision == SignalDecision.REJECT_EDGE_NEGATIVE
    assert score.reasons
