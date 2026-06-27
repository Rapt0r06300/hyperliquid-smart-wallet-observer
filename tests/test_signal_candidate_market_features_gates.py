"""Proof that MarketSignalFeatures actually INFLUENCE the decision.

detect_signal_candidates now forwards per-coin spread_bps / liquidity_score /
current_mid into build_signal_candidate's gates. No network, deterministic.
"""

from __future__ import annotations

from types import SimpleNamespace

from hyper_smart_observer.copy_mode.copy_models import PositionView, SignalDecision, utc_now
from hyper_smart_observer.copy_mode.copy_signal_detector import detect_signal_candidates
from hyper_smart_observer.copy_mode.delta_detector import diff_position_snapshots

ADDR = "0x" + "a" * 40


def _open_long():
    now = utc_now()
    return diff_position_snapshots(
        [PositionView(ADDR, "BTC", 0, now, 50_000)],
        [PositionView(ADDR, "BTC", 1, now, 50_010)],
        observed_at=now,
    )[0]


def _feat(**kw):
    base = dict(current_mid=50_000.0, spread_bps=2.0, liquidity_score=1.0)
    base.update(kw)
    return SimpleNamespace(**base)


def _detect(feature):
    return detect_signal_candidates(
        [_open_long()],
        leader_expected_edge_bps=100.0,
        leader_scores={ADDR: 95.0},
        market_features={"BTC": feature},
    )


def test_low_liquidity_feature_forces_no_trade():
    signals, _ = _detect(_feat(liquidity_score=0.1))
    assert signals[0].decision == SignalDecision.REJECT_NO_TRADE
    assert "LIQUIDITY_TOO_LOW" in signals[0].refusal_reasons


def test_wide_spread_feature_forces_no_trade():
    signals, _ = _detect(_feat(spread_bps=60.0))
    assert signals[0].decision == SignalDecision.REJECT_NO_TRADE
    assert "SPREAD_TOO_WIDE" in signals[0].refusal_reasons


def test_good_features_not_rejected_for_liquidity_or_spread():
    signals, _ = _detect(_feat())
    assert "LIQUIDITY_TOO_LOW" not in signals[0].refusal_reasons
    assert "SPREAD_TOO_WIDE" not in signals[0].refusal_reasons
