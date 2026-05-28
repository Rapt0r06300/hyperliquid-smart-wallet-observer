import os
import sys
from datetime import datetime, UTC

# Ensure project root is in path
sys.path.append(os.getcwd())

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
from hyper_smart_observer.copy_mode.copy_models import LeaderStatus, LeaderShortlistEntry, LeaderboardShortlistReport
from hyper_smart_observer.copy_mode.leaderboard_selector import write_shortlist_report
from tests.helpers.fake_hyperliquid_info_client import FakeHyperliquidInfoClient

def showcase():
    print("=== HYPERSMART PIPELINE SHOWCASE (DRY-RUN) ===\n")

    # 1. Temporary directory for showcase
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        config = AppConfig(
            database_path=tmp_path / "showcase.sqlite3",
            runtime_root=tmp_path,
            reports_dir=tmp_path / "reports",
            copy_max_leaders_per_run=3
        )

        # 2. Setup a fake shortlist
        shortlist_dir = tmp_path / "data"
        shortlist_dir.mkdir(parents=True)
        shortlist_file = shortlist_dir / "leaderboard_shortlist.json"

        leader_addr = "0x1111111111111111111111111111111111111111"
        entry = LeaderShortlistEntry(
            wallet_address=leader_addr,
            status=LeaderStatus.SHORTLISTED,
            score=95.0,
            source="showcase"
        )
        write_shortlist_report(
            LeaderboardShortlistReport(datetime.now(UTC), 5, 1, [entry]),
            shortlist_file
        )
        print(f"1. Shortlist created for {leader_addr}")

        # 3. Run the loop with fake client
        print("2. Running copy-run with FakeHyperliquidInfoClient (using fixtures)...")
        fake_client = FakeHyperliquidInfoClient()
        report = run_copy_dry_run(
            config,
            interval_seconds=300,
            network_read=True,
            info_client=fake_client
        )

        # 4. Display Results
        print("\n--- Showcase Report Summary ---")
        print(f"Leaders Seen: {report.leaders_seen}")
        print(f"Deltas Detected: {report.deltas_seen}")
        print(f"Signal Candidates: {len(report.signal_candidates)}")

        if report.signal_candidates:
            sig = report.signal_candidates[0]
            print(f"\nExample Signal:")
            print(f"  - Wallet: {sig.leader_wallet}")
            print(f"  - Action: {sig.action_type.value}")
            print(f"  - Coin: {sig.coin}")
            print(f"  - Edge Remaining: {sig.edge_remaining_bps} bps")
            print(f"  - Decision: {sig.decision.value}")

        if report.no_trade_decisions:
            print(f"\nNo-Trade Decisions: {len(report.no_trade_decisions)}")
            for nt in report.no_trade_decisions[:3]:
                print(f"  - {nt.reason.value}: {nt.observed} -> {nt.next_action}")

        print("\nPipeline execution finished successfully (Paper Mock USDC).")

if __name__ == "__main__":
    showcase()
