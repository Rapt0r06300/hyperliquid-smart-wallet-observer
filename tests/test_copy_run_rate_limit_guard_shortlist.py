"""shortlist > max_leaders => RATE_LIMIT_GUARD, bounded scan, no PaperIntent.

Hyperliquid rate limits forbid following an unbounded shortlist. run_copy_dry_run
caps the observed leaders and records a RATE_LIMIT_GUARD NoTradeDecision.
No network (network_read=False), SQLite tmp.
"""

from __future__ import annotations

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run, shortlist_path
from hyper_smart_observer.copy_mode.copy_models import LeaderCandidateInput, NoTradeReason
from hyper_smart_observer.copy_mode.leaderboard_selector import (
    LeaderboardSelectionConfig,
    select_leaderboard_shortlist,
    write_shortlist_report,
)


def _cand(addr: str) -> LeaderCandidateInput:
    return LeaderCandidateInput(
        wallet_address=addr,
        history_days=30,
        closed_pnl_points=50,
        total_closed_pnl=1000.0,
        max_single_trade_pnl=100.0,
        max_drawdown_pct=10.0,
        consistency_score=90.0,
        per_coin_stability_score=85.0,
        execution_quality_score=85.0,
        sample_confidence=90.0,
        copyability_score=90.0,
    )


def test_shortlist_over_max_leaders_emits_rate_limit_guard(tmp_path):
    config = AppConfig(
        runtime_root=tmp_path,
        database_path=tmp_path / "data" / "hs.sqlite3",
        reports_dir=tmp_path / "data" / "reports",
        dashboard_dir=tmp_path / "data" / "dashboard",
    )
    addrs = ["0x" + c * 40 for c in "abcde"]  # 5 distinct valid wallets
    report = select_leaderboard_shortlist(
        [_cand(a) for a in addrs], config=LeaderboardSelectionConfig(min_score=1)
    )
    write_shortlist_report(report, shortlist_path(config))

    run = run_copy_dry_run(config, interval_seconds=300, network_read=False, max_leaders=2)

    assert any(d.reason == NoTradeReason.RATE_LIMIT_GUARD for d in run.no_trade_decisions)
    # Bounded: no signal candidate / no paper intent without network-read evidence.
    assert not run.signal_candidates
