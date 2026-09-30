"""The scan-features export (dashboard feature payload) carries REAL l2Book-derived
market features and no fabricated data. No network."""

from __future__ import annotations

import json
from pathlib import Path

from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
from hyper_smart_observer.dashboard.exporter import export_dashboard
from tests.hl_runtime_fakes import RuntimeFakeInfoClient, healthy_l2, runtime_config, write_leader_shortlist


def test_export_carries_real_market_features_and_no_fake(tmp_path):
    config = runtime_config(tmp_path)
    write_leader_shortlist(config)
    fake = RuntimeFakeInfoClient(l2_book=healthy_l2())

    run = run_copy_dry_run(config, interval_seconds=300, network_read=True, info_client=fake)

    assert run.scan_features_rows >= 1
    rows = json.loads(Path(run.scan_features_json_path).read_text(encoding="utf-8"))
    btc = [r for r in rows if r.get("symbol") == "BTC"]
    assert btc, "no BTC market features exported"
    row = btc[0]
    assert row["mid_source"] in ("MID_FROM_BOOK", "MID_FROM_LAST_TRADE_FALLBACK", "MID_MISSING")
    assert isinstance(row["spread_bps"], (int, float))
    assert isinstance(row["liquidity_score"], (int, float))
    assert row["data_quality"] in ("OK", "DEGRADED", "STALE", "MISSING", "SOURCE_DEGRADED")
    raw = Path(run.scan_features_json_path).read_text(encoding="utf-8").lower()
    assert "math.random" not in raw and "fakeposition" not in raw and "dummyequity" not in raw

    # The HTML dashboard itself fabricates nothing.
    html = export_dashboard(config).read_text(encoding="utf-8").lower()
    assert "math.random" not in html and "fakeposition" not in html
