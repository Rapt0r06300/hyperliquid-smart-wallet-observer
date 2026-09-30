from hl_observer.copying.leaderboard_autoselect import CopyLeaderAutoSelectConfig, evaluate_copy_leader_candidate, select_copy_leaders
from hl_observer.wallets.leaderboard_models import LeaderboardCandidate


def _candidate(address: str, **kwargs) -> LeaderboardCandidate:
    payload = {
        "wallet_address": address,
        "rank": kwargs.pop("rank", 1),
        "period": kwargs.pop("period", "30D"),
        "pnl_usdc": kwargs.pop("pnl_usdc", 250_000.0),
        "roi_pct": kwargs.pop("roi_pct", 35.0),
        "volume_usdc": kwargs.pop("volume_usdc", 5_000_000.0),
        "leaderboard_score": kwargs.pop("leaderboard_score", 95.0),
        "source_confidence": kwargs.pop("source_confidence", 90.0),
    }
    payload.update(kwargs)
    return LeaderboardCandidate(**payload)


def test_leaderboard_autoselect_accepts_top_full_address():
    report = select_copy_leaders(
        [_candidate("0x" + "a" * 40)],
        config=CopyLeaderAutoSelectConfig(top_n=5),
    )

    assert report.accepted_count == 1
    assert report.accepted[0].reasons == ["accepted_for_paper_copy_research"]
    assert report.mode == "PAPER_MOCK_USDC_ONLY"


def test_leaderboard_autoselect_rejects_truncated_address():
    selection = evaluate_copy_leader_candidate(_candidate("0xaaaa...bbbb"))

    assert not selection.accepted
    assert "invalid_or_truncated_address" in selection.reasons


def test_leaderboard_autoselect_rejects_short_history():
    selection = evaluate_copy_leader_candidate(_candidate("0x" + "b" * 40, period="1D"))

    assert not selection.accepted
    assert "history_window_too_short" in selection.reasons


def test_leaderboard_autoselect_rejects_concentrated_pnl():
    selection = evaluate_copy_leader_candidate(
        _candidate("0x" + "c" * 40),
        pnl_concentration=0.92,
        config=CopyLeaderAutoSelectConfig(max_pnl_concentration=0.65),
    )

    assert not selection.accepted
    assert "pnl_too_concentrated" in selection.reasons


def test_leaderboard_autoselect_limits_to_top_five():
    candidates = [_candidate("0x" + format(i, "040x"), rank=i, leaderboard_score=100 - i) for i in range(8)]

    report = select_copy_leaders(candidates, config=CopyLeaderAutoSelectConfig(top_n=5))

    assert report.accepted_count == 5
    assert len(report.rejected) == 3
    assert any("outside_top_n" in row.reasons for row in report.rejected)
