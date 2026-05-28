import pytest
import os
from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
from hyper_smart_observer.copy_mode.copy_models import LeaderStatus, LeaderShortlistEntry, LeaderboardShortlistReport
from hyper_smart_observer.copy_mode.leaderboard_selector import write_shortlist_report
from tests.helpers.fake_hyperliquid_info_client import FakeHyperliquidInfoClient

@pytest.mark.contract
def test_contract_copy_run_logic_flow(tmp_path):
    """
    Contract: Verify that run_copy_dry_run processes deltas using a fake client.
    This ensures the pipeline logic is decoupled from the network.
    """
    config = AppConfig(
        database_path=tmp_path / "test_logic.sqlite3",
        runtime_root=tmp_path,
        reports_dir=tmp_path / "reports",
        copy_max_leaders_per_run=3
    )

    # 1. Setup a fake shortlist
    shortlist_dir = tmp_path / "data"
    shortlist_dir.mkdir(parents=True)
    shortlist_file = shortlist_dir / "leaderboard_shortlist.json"

    leader_addr = "0x1111111111111111111111111111111111111111"
    entry = LeaderShortlistEntry(
        wallet_address=leader_addr,
        status=LeaderStatus.SHORTLISTED,
        score=90.0,
        source="test"
    )
    from datetime import datetime, UTC
    write_shortlist_report(
        LeaderboardShortlistReport(datetime.now(UTC), 5, 1, [entry]),
        shortlist_file
    )

    # 2. Run the loop with fake client
    fake_client = FakeHyperliquidInfoClient()
    report = run_copy_dry_run(
        config,
        interval_seconds=300,
        network_read=True,
        info_client=fake_client
    )

    # 3. Assertions
    assert report.leaders_seen == 1
    # The fake client returns BTC position 0.1 (OPEN_LONG if prev was 0)
    # Our DB is empty, so prev is 0.
    assert report.deltas_seen >= 1

    # Check if a signal candidate was produced
    assert len(report.signal_candidates) >= 1
    signal = report.signal_candidates[0]
    assert signal.leader_wallet.lower() == leader_addr.lower()
    assert signal.coin == "BTC"
