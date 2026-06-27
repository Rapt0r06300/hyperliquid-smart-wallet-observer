"""Backtest/runtime parity: the SAME objects (MarketSignalFeatures, LeaderDelta,
SignalCandidate, EdgeCalculator gates) produce the SAME reason code in the live
runtime path and in a direct replay. No network."""

from __future__ import annotations

from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
from hyper_smart_observer.copy_mode.copy_models import PositionView, utc_now
from hyper_smart_observer.copy_mode.copy_signal_detector import detect_signal_candidates
from hyper_smart_observer.copy_mode.delta_detector import diff_position_snapshots
from hyper_smart_observer.market_signals.market_signal_features import build_market_signal_features
from tests.hl_runtime_fakes import LEADER, RuntimeFakeInfoClient, runtime_config, thin_l2, write_leader_shortlist


def _runtime_reason(tmp_path):
    config = runtime_config(tmp_path)
    write_leader_shortlist(config)
    run = run_copy_dry_run(
        config, interval_seconds=300, network_read=True,
        info_client=RuntimeFakeInfoClient(l2_book=thin_l2()),
    )
    reasons = set()
    for s in run.signal_candidates:
        reasons |= set(s.refusal_reasons)
    return reasons


def _replay_reason():
    feat = build_market_signal_features(
        timestamp_ms=1, symbol="BTC", l2_book=thin_l2(), all_mids={"BTC": "50000.0"}
    )
    now = utc_now()
    delta = diff_position_snapshots(
        [PositionView(LEADER, "BTC", 0, now, 50_000)],
        [PositionView(LEADER, "BTC", 1, now, 50_010)],
        observed_at=now,
    )[0]
    signals, _ = detect_signal_candidates(
        [delta], leader_expected_edge_bps=100.0,
        leader_scores={LEADER: 95.0}, market_features={"BTC": feat},
    )
    return set(signals[0].refusal_reasons)


def test_low_liquidity_reason_code_is_identical_runtime_vs_replay(tmp_path):
    runtime_reasons = _runtime_reason(tmp_path)
    replay_reasons = _replay_reason()
    assert "LIQUIDITY_TOO_LOW" in runtime_reasons
    assert "LIQUIDITY_TOO_LOW" in replay_reasons
    assert "LIQUIDITY_TOO_LOW" in (runtime_reasons & replay_reasons)
