from __future__ import annotations

from datetime import timedelta

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run, shortlist_path
from hyper_smart_observer.copy_mode.copy_models import (
    DeltaAction,
    FillView,
    LeaderCandidateInput,
    LeaderStatus,
    NoTradeReason,
    PositionView,
    utc_now,
)
from hyper_smart_observer.copy_mode.copy_signal_detector import detect_signal_candidates
from hyper_smart_observer.copy_mode.delta_detector import classify_fill_delta, classify_position_delta, diff_position_snapshots
from hyper_smart_observer.copy_mode.edge import price_deviation_penalty_bps
from hyper_smart_observer.copy_mode.leaderboard_selector import LeaderboardSelectionConfig, select_leaderboard_shortlist, write_shortlist_report
from hyper_smart_observer.copy_mode.no_trade_report import decision_from_reason, format_no_trade_markdown
from hyper_smart_observer.copy_mode.signal_candidate import build_signal_candidate
from hyper_smart_observer.dashboard.exporter import export_dashboard


GOOD_ADDRESS = "0x" + "a" * 40


def _candidate(address: str = GOOD_ADDRESS, **kwargs) -> LeaderCandidateInput:
    payload = {
        "wallet_address": address,
        "history_days": 30,
        "closed_pnl_points": 42,
        "total_closed_pnl": 10_000.0,
        "max_single_trade_pnl": 1_000.0,
        "max_drawdown_pct": 12.0,
        "consistency_score": 82.0,
        "per_coin_stability_score": 75.0,
        "execution_quality_score": 78.0,
        "sample_confidence": 85.0,
        "copyability_score": 80.0,
    }
    payload.update(kwargs)
    return LeaderCandidateInput(**payload)


def test_shortlist_rejects_truncated_and_invalid_addresses():
    report = select_leaderboard_shortlist(
        [_candidate("0xaaaa...bbbb"), _candidate("not-a-wallet")],
        config=LeaderboardSelectionConfig(min_score=1),
    )

    reasons = [reason for entry in report.entries for reason in entry.refusal_reasons]
    assert "TRUNCATED_ADDRESS_REJECTED" in reasons
    assert "INVALID_ADDRESS_REJECTED" in reasons
    assert not report.shortlisted


def test_shortlist_rejects_one_big_win_and_pnl_concentration():
    report = select_leaderboard_shortlist(
        [_candidate(max_single_trade_pnl=9_000.0, total_closed_pnl=10_000.0)],
        config=LeaderboardSelectionConfig(min_score=1),
    )

    assert report.entries[0].status == LeaderStatus.REJECTED
    assert "PNL_CONCENTRATION_TOO_HIGH" in report.entries[0].refusal_reasons
    assert "ONE_BIG_WIN_RISK" in report.entries[0].refusal_reasons


def test_shortlist_accepts_sufficient_wallet():
    report = select_leaderboard_shortlist([_candidate()], config=LeaderboardSelectionConfig(min_score=1))

    assert report.shortlisted
    assert report.shortlisted[0].wallet_address == GOOD_ADDRESS


def test_position_delta_detector_open_add_reduce_close_and_flip_unknown():
    assert classify_position_delta(0, 1)[0] == DeltaAction.OPEN_LONG
    assert classify_position_delta(0, -1)[0] == DeltaAction.OPEN_SHORT
    assert classify_position_delta(1, 2)[0] == DeltaAction.INCREASE
    assert classify_position_delta(-1, -2)[0] == DeltaAction.INCREASE
    assert classify_position_delta(2, 1)[0] == DeltaAction.REDUCE
    assert classify_position_delta(-2, -1)[0] == DeltaAction.REDUCE
    assert classify_position_delta(1, 0)[0] == DeltaAction.CLOSE_LONG
    assert classify_position_delta(-1, 0)[0] == DeltaAction.CLOSE_SHORT
    action, warnings = classify_position_delta(1, -1)
    assert action == DeltaAction.UNKNOWN
    assert "flip_detected_batch1_unknown" in warnings


def test_fill_delta_detector_open_add_reduce_close_and_unknown():
    assert classify_fill_delta(FillView(GOOD_ADDRESS, "BTC", "Open Long", start_position=0))[0] == DeltaAction.OPEN_LONG
    assert classify_fill_delta(FillView(GOOD_ADDRESS, "BTC", "Open Short", start_position=0))[0] == DeltaAction.OPEN_SHORT
    assert classify_fill_delta(FillView(GOOD_ADDRESS, "BTC", "Open Long", start_position=1))[0] == DeltaAction.ADD
    assert classify_fill_delta(FillView(GOOD_ADDRESS, "BTC", "Close Long"), current_position_size=0)[0] == DeltaAction.CLOSE_LONG
    assert classify_fill_delta(FillView(GOOD_ADDRESS, "BTC", "Close Short"), current_position_size=-0.5)[0] == DeltaAction.REDUCE
    assert classify_fill_delta(FillView(GOOD_ADDRESS, "BTC", "???"))[0] == DeltaAction.UNKNOWN


def test_signal_candidate_requires_edge_remaining():
    now = utc_now()
    delta = diff_position_snapshots(
        [PositionView(GOOD_ADDRESS, "BTC", 0, now, 50_000)],
        [PositionView(GOOD_ADDRESS, "BTC", 1, now, 50_010)],
        observed_at=now,
    )[0]
    signal = build_signal_candidate(
        delta,
        leader_expected_edge_bps=None,
        current_mid=50_020,
        leader_score=90,
    )

    assert signal.decision.value == "REJECT_NO_TRADE"
    assert signal.edge_remaining_bps is None
    assert "EDGE_UNMEASURABLE" in signal.refusal_reasons


def test_signal_candidate_rejects_stale_low_edge_bad_liquidity():
    old = utc_now() - timedelta(minutes=10)
    delta = diff_position_snapshots(
        [PositionView(GOOD_ADDRESS, "BTC", 0, old, 50_000)],
        [PositionView(GOOD_ADDRESS, "BTC", 1, old, 50_010)],
        observed_at=old,
    )[0]
    signal = build_signal_candidate(
        delta,
        leader_expected_edge_bps=5,
        current_mid=50_020,
        leader_score=20,
        observed_at=utc_now(),
        spread_bps=30,
        slippage_bps=35,
        liquidity_score=0.1,
    )

    assert signal.decision.value == "REJECT_NO_TRADE"
    assert "STALE_SIGNAL" in signal.refusal_reasons
    assert "EDGE_REMAINING_TOO_LOW" in signal.refusal_reasons
    assert "LIQUIDITY_TOO_LOW" in signal.refusal_reasons


def test_price_deviation_penalty_detects_late_worse_copy_prices():
    assert price_deviation_penalty_bps(DeltaAction.OPEN_LONG, 100.0, 101.0) == 100.0
    assert price_deviation_penalty_bps(DeltaAction.OPEN_LONG, 100.0, 99.0) == 0.0
    assert price_deviation_penalty_bps(DeltaAction.OPEN_SHORT, 100.0, 99.0) == 100.0
    assert price_deviation_penalty_bps(DeltaAction.OPEN_SHORT, 100.0, 101.0) == 0.0


def test_close_without_matching_paper_position_is_no_trade():
    now = utc_now()
    delta = diff_position_snapshots(
        [PositionView(GOOD_ADDRESS, "BTC", 1, now, 50_000)],
        [PositionView(GOOD_ADDRESS, "BTC", 0, now, 50_010)],
        observed_at=now,
    )[0]
    signals, no_trade = detect_signal_candidates([delta], leader_expected_edge_bps=50)

    assert signals == []
    assert no_trade[0].reason == NoTradeReason.NO_MATCHING_PAPER_POSITION_FOR_CLOSE


def test_no_trade_report_is_french_and_actionable():
    decision = decision_from_reason(
        NoTradeReason.EDGE_REMAINING_TOO_LOW,
        observed="OPEN_LONG BTC observe",
        leader_wallet=GOOD_ADDRESS,
        coin="BTC",
    )
    text = format_no_trade_markdown([decision])

    assert "Pourquoi" in text
    assert "Action suivante" in text
    assert "EDGE_REMAINING_TOO_LOW" in text


def test_copy_run_creates_shortlist_and_no_trade_outputs(tmp_path):
    config = AppConfig(runtime_root=tmp_path, database_path=tmp_path / "data" / "hypersmart.sqlite3", reports_dir=tmp_path / "data" / "reports")
    report = run_copy_dry_run(config, interval_seconds=300, network_read=False)

    assert report.dry_run is True
    assert shortlist_path(config).exists()
    assert (config.reports_dir / "no_trade_report.md").exists()
    assert any(decision.reason == NoTradeReason.NETWORK_READ_DISABLED for decision in report.no_trade_decisions)


def test_dashboard_contains_copy_sections_readonly(tmp_path):
    config = AppConfig(runtime_root=tmp_path, database_path=tmp_path / "data" / "hypersmart.sqlite3", dashboard_dir=tmp_path / "data" / "dashboard")
    write_shortlist_report(
        select_leaderboard_shortlist([_candidate()], config=LeaderboardSelectionConfig(min_score=1)),
        shortlist_path(config),
    )
    run_copy_dry_run(config, network_read=False)
    html_path = export_dashboard(config)
    html = html_path.read_text(encoding="utf-8").lower()

    assert "copy status" in html
    assert "leaderboard shortlist" in html
    assert "no-trade report" in html
    assert "edge remaining" in html
    assert "<button" not in html
    assert "private key" not in html
