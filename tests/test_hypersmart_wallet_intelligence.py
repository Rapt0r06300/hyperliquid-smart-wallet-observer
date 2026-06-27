from __future__ import annotations

from hyper_smart_observer.intelligence.wallet_intelligence import analyze_wallet_pnls


def test_wallet_intelligence_penalizes_one_big_win_and_concentration() -> None:
    report = analyze_wallet_pnls("0x" + "1" * 40, [1000, 5, -3, 4, -1, 2, 1, 3, -2, 4])

    assert report.one_big_win is True
    assert "ONE_BIG_WIN_RISK" in report.risk_flags
    assert "PNL_CONCENTRATION_TOO_HIGH" in report.risk_flags
    assert report.status == "WATCH_ONLY"


def test_wallet_intelligence_allows_more_regular_sample() -> None:
    report = analyze_wallet_pnls("0x" + "2" * 40, [12, 8, -4, 9, 7, -3, 11, 6, -2, 5, 4, -1])

    assert report.one_big_win is False
    assert report.trades == 12
    assert report.winrate > 0.6
    assert report.copyability_score > 0
