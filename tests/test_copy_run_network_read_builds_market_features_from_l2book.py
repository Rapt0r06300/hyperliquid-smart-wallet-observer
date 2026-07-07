"""Runtime proof: run_copy_dry_run fetches l2Book per active coin and feeds the
resulting MarketSignalFeatures into detect_signal_candidates. Healthy book =>
liquidity gate (fed by real l2Book) does NOT block. No network."""

from __future__ import annotations

import json
from pathlib import Path

from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
from tests.hl_runtime_fakes import RuntimeFakeInfoClient, healthy_l2, runtime_config, write_leader_shortlist


def test_runtime_builds_features_from_l2book_and_healthy_not_blocked(tmp_path):
    config = runtime_config(tmp_path)
    write_leader_shortlist(config)
    fake = RuntimeFakeInfoClient(l2_book=healthy_l2())

    run = run_copy_dry_run(config, interval_seconds=300, network_read=True, info_client=fake)

    assert "l2Book" in fake.calls          # l2Book fetched in the runtime path
    assert "candleSnapshot" in fake.calls  # volatility fetched read-only in the runtime path
    assert run.deltas_seen >= 1
    assert run.signal_candidates           # a candidate was evaluated
    assert run.scan_features_json_path is not None
    assert run.decision_ledger_entries >= 1
    assert run.decision_ledger_json_path is not None
    rows = json.loads(Path(run.scan_features_json_path).read_text(encoding="utf-8"))
    ledger = json.loads(Path(run.decision_ledger_json_path).read_text(encoding="utf-8"))
    assert rows[0]["volatility_realized_bps"] is not None
    assert rows[0]["volatility_atr_bps"] is not None
    assert rows[0]["volatility_bucket"] in {"LOW", "NORMAL", "HIGH", "EXTREME"}
    assert rows[0]["volatility_data_quality"] == "OK"
    assert any(row["feature_hash"] for row in ledger if row["coin"] == "BTC")
    assert any("candleSnapshot" in row["raw_refs"] for row in ledger if row["coin"] == "BTC")
    assert all("LIQUIDITY_TOO_LOW" not in s.refusal_reasons for s in run.signal_candidates)
    assert all("SPREAD_TOO_WIDE" not in s.refusal_reasons for s in run.signal_candidates)
