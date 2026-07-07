"""Evidence chain: every exported market feature carries a reproducible SHA-256
hash, and a runtime decision's coin is auditable in the feature export."""

from __future__ import annotations

import json
from pathlib import Path

from hyper_smart_observer.copy_mode.copy_loop import run_copy_dry_run
from hyper_smart_observer.market_signals.market_signal_features import build_market_signal_features
from tests.hl_runtime_fakes import RuntimeFakeInfoClient, healthy_l2, runtime_config, write_leader_shortlist


def test_feature_hash_is_deterministic_and_prefixed():
    book = healthy_l2()
    f1 = build_market_signal_features(timestamp_ms=1, source_ts=1, symbol="BTC", l2_book=book, all_mids={"BTC": "50000.0"})
    f2 = build_market_signal_features(timestamp_ms=1, source_ts=1, symbol="BTC", l2_book=book, all_mids={"BTC": "50000.0"})
    assert f1.feature_hash.startswith("feat:")
    assert f1.feature_hash == f2.feature_hash  # reproducible evidence ref


def test_runtime_decision_coin_is_auditable_in_feature_export(tmp_path):
    cfg = runtime_config(tmp_path)
    write_leader_shortlist(cfg)
    run = run_copy_dry_run(cfg, interval_seconds=300, network_read=True, info_client=RuntimeFakeInfoClient(l2_book=healthy_l2()))

    rows = json.loads(Path(run.scan_features_json_path).read_text(encoding="utf-8"))
    assert rows, "no feature rows exported"
    assert all(str(r["feature_hash"]).startswith("feat:") for r in rows)

    decision_coins = {s.coin.upper() for s in run.signal_candidates}
    decision_coins |= {d.coin.upper() for d in run.no_trade_decisions if getattr(d, "coin", None)}
    feature_coins = {str(r["symbol"]).upper() for r in rows}
    assert decision_coins & feature_coins  # the decided coin maps to a feature row
