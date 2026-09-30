"""Phase 3: DecisionLedger evidence chain.

Every runtime decision becomes a ledger entry linking decision_id -> the exact
market feature snapshot (feature_hash) + reason codes + read-only source refs,
with a reproducible evidence_hash, persisted to JSON/CSV and retrievable.
No orders, no execution, simulation evidence only.
"""

from __future__ import annotations

from hyper_smart_observer.copy_mode.copy_loop import _market_features_by_coin, run_copy_dry_run
from hyper_smart_observer.ledger import (
    build_decision_ledger,
    feature_hash_for_decision,
    load_decision_ledger,
    write_decision_ledger,
)
from tests.hl_runtime_fakes import RuntimeFakeInfoClient, runtime_config, thin_l2, write_leader_shortlist


def _run_and_features(tmp_path):
    cfg = runtime_config(tmp_path)
    write_leader_shortlist(cfg)
    run = run_copy_dry_run(cfg, interval_seconds=300, network_read=True, info_client=RuntimeFakeInfoClient(l2_book=thin_l2()))
    feats = _market_features_by_coin(
        info_client=RuntimeFakeInfoClient(l2_book=thin_l2()),
        all_mids={"BTC": "50000.0"}, coins=["BTC"],
        l2_cache={}, candle_cache={}, source_failures=[],
    )
    return cfg, run, feats


def test_every_decision_has_minimal_evidence_and_feature_link(tmp_path):
    cfg, run, feats = _run_and_features(tmp_path)
    entries = build_decision_ledger(run.signal_candidates, run.no_trade_decisions, feats, run_id="scan:run/1")
    assert entries, "no ledger entries built"
    for e in entries:
        assert e.decision_id and e.decision_type
        assert e.reason_codes or e.feature_hash  # never a decision without evidence
        assert e.evidence_hash.startswith("ev:")
    btc = [e for e in entries if e.coin == "BTC" and e.feature_hash]
    assert btc, "no BTC decision linked to a feature_hash"
    assert btc[0].feature_hash == feats["BTC"].feature_hash  # exact feature used


def test_evidence_hash_reproducible_and_roundtrip_retrieval(tmp_path):
    cfg, run, feats = _run_and_features(tmp_path)
    e1 = build_decision_ledger(run.signal_candidates, run.no_trade_decisions, feats, run_id="r1")
    e2 = build_decision_ledger(run.signal_candidates, run.no_trade_decisions, feats, run_id="r1")
    assert [e.evidence_hash for e in e1] == [e.evidence_hash for e in e2]  # reproducible

    res = write_decision_ledger(e1, cfg.reports_dir / "decision_ledger", run_id="r1")
    loaded = load_decision_ledger(res.json_path)
    assert len(loaded) == len(e1)
    with_feat = next(e for e in e1 if e.feature_hash)
    assert feature_hash_for_decision(loaded, with_feat.decision_id) == with_feat.feature_hash
