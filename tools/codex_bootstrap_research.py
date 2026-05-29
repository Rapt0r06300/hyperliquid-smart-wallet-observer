import os
import sys
import shutil
from pathlib import Path
from datetime import datetime, UTC

# Ensure project root is in path
sys.path.append(os.getcwd())

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run, shortlist_path
from hyper_smart_observer.copy_mode.copy_models import LeaderStatus, LeaderShortlistEntry, LeaderboardShortlistReport
from hyper_smart_observer.copy_mode.leaderboard_selector import write_shortlist_report
from hyper_smart_observer.storage.database import initialize_database, get_connection
from tests.helpers.fake_hyperliquid_info_client import FakeHyperliquidInfoClient

def bootstrap():
    print("=== CODEX BOOTSTRAP RESEARCH TOOL ===")

    # 1. Setup Research Root
    research_root = Path("data/research_bootstrap")
    if research_root.exists():
        shutil.rmtree(research_root)
    research_root.mkdir(parents=True)

    config = AppConfig(
        database_path=research_root / "research.sqlite3",
        runtime_root=research_root,
        reports_dir=research_root / "reports"
    )

    # 2. Initialize Database
    print("1. Initializing Research Database...")
    initialize_database(config)

    # 3. Seed Shortlist with Fixture Data
    print("2. Seeding Shortlist (Leader Alpha & Beta)...")
    shortlist_file = shortlist_path(config)
    shortlist_file.parent.mkdir(parents=True, exist_ok=True)

    leaders = [
        LeaderShortlistEntry(
            wallet_address="0x1111111111111111111111111111111111111111",
            status=LeaderStatus.SHORTLISTED,
            score=95.0,
            source="bootstrap"
        ),
        LeaderShortlistEntry(
            wallet_address="0x2222222222222222222222222222222222222222",
            status=LeaderStatus.SHORTLISTED,
            score=82.0,
            source="bootstrap"
        )
    ]
    write_shortlist_report(
        LeaderboardShortlistReport(datetime.now(UTC), 5, 2, leaders),
        shortlist_file
    )

    # 4. Run First Research Cycle (Mocked)
    print("3. Running Initial Research Cycle (Mock Info Client)...")
    fake_client = FakeHyperliquidInfoClient()
    report = run_copy_dry_run(
        config,
        interval_seconds=300,
        network_read=True,
        info_client=fake_client
    )

    print("\n--- Bootstrap Results ---")
    print(f"Research Root: {research_root}")
    print(f"Deltas Found: {report.deltas_seen}")
    print(f"Signals Found: {len(report.signal_candidates)}")
    print(f"Ledger created: {research_root / 'data' / 'research_history_ledger.jsonl'}")

    print("\n[SUCCESS] Environment is bootstrapped. Codex can now run research commands.")

if __name__ == "__main__":
    bootstrap()
