import pytest
from pathlib import Path
import json
from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run, shortlist_path
from tests.helpers.fake_hyperliquid_info_client import FakeHyperliquidInfoClient

def test_copy_pipeline_with_fake_client(tmp_path):
    # Setup config with tmp_path as runtime_root
    config = AppConfig(
        runtime_root=tmp_path,
        database_path=tmp_path / "hypersmart_test.sqlite3",
        reports_dir=tmp_path / "reports",
        enable_network_reads=True,
        copy_max_leaders_per_run=3
    )

    # Create data directory and shortlist
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    shortlist_file = data_dir / "leaderboard_shortlist.json"

    shortlist_data = {
      "generated_at": "2026-05-24T10:00:00Z",
      "entries": [
        {
          "wallet_address": "0x1111111111111111111111111111111111111111",
          "status": "SHORTLISTED",
          "score": 85.5
        }
      ]
    }
    shortlist_file.write_text(json.dumps(shortlist_data))

    fake_client = FakeHyperliquidInfoClient(config)

    report = run_copy_dry_run(
        config,
        network_read=True,
        info_client=fake_client,
        max_leaders=3
    )

    assert report.leaders_seen == 1
    assert fake_client.call_counts["get_all_mids"] >= 1
    assert fake_client.call_counts["get_clearinghouse_state"] >= 1
    assert report.dry_run is True
    assert len(report.source_failures) == 0
