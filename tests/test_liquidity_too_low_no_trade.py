"""Low l2Book liquidity_score => LIQUIDITY_TOO_LOW => NoTrade (no PaperIntent)."""

from __future__ import annotations

from types import SimpleNamespace

from hyper_smart_observer.copy_mode.copy_models import PositionView, SignalDecision, utc_now
from hyper_smart_observer.copy_mode.copy_signal_detector import detect_signal_candidates
from hyper_smart_observer.copy_mode.delta_detector import diff_position_snapshots

ADDR = "0x" + "b" * 40


def test_low_liquidity_blocks_paper_intent():
    now = utc_now()
    delta = diff_position_snapshots(
        [PositionView(ADDR, "ETH", 0, now, 3_000)],
        [PositionView(ADDR, "ETH", 1, now, 3_001)],
        observed_at=now,
    )[0]
    feature = SimpleNamespace(current_mid=3_000.0, spread_bps=3.0, liquidity_score=0.05)
    signals, no_trade = detect_signal_candidates(
        [delta],
        leader_expected_edge_bps=120.0,
        leader_scores={ADDR: 99.0},
        market_features={"ETH": feature},
    )
    assert signals[0].decision == SignalDecision.REJECT_NO_TRADE
    assert "LIQUIDITY_TOO_LOW" in signals[0].refusal_reasons
    assert not any(s.decision == SignalDecision.ACCEPT_PAPER for s in signals)
