from types import SimpleNamespace

from hl_observer.copying.leaderboard_autoselect import CopyLeaderAutoSelectReport
from hl_observer.copying.reports import format_copy_run_report
from hl_observer.copying.signal_detector import CopySignalDetectionReport


def test_format_copy_run_report_covers_leaders_reasons_and_signal_details() -> None:
    leaders = CopyLeaderAutoSelectReport(
        target_leaders=2,
        candidates_seen=3,
        accepted=[],
        rejected=[],
    )
    signal = SimpleNamespace(
        id="sig-1",
        source_wallet="0xabc",
        coin="BTC",
        signal_type="OPEN",
        side="LONG",
        edge_remaining_bps=12.34,
        decision=SimpleNamespace(value="PAPER_TRADE"),
    )
    signals = CopySignalDetectionReport.model_construct(
        interval_seconds=60,
        deltas_seen=4,
        signals_created=1,
        paper_candidates=1,
        rejected=0,
        no_trade_reasons={"wallet_not_followed": 2, "price_missing": 1},
        signals=[signal],
    )

    report = format_copy_run_report(leaders=leaders, signals=signals)

    assert "leaderboard candidates seen: 3" in report
    assert "leaders auto-selected: 0/2" in report
    assert "no-trade reasons:" in report
    assert "- price_missing: 1" in report
    assert "- wallet_not_followed: 2" in report
    assert "- sig-1 0xabc BTC OPEN/LONG edge=12.3 decision=PAPER_TRADE" in report
