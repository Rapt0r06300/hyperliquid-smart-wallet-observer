"""Phase 3 (canonical): a persisted decision can be fully reconstructed from evidence."""

from __future__ import annotations

from hyper_smart_observer.copy_mode.copy_loop import _market_features_by_coin, run_copy_dry_run
from hyper_smart_observer.ledger.decision_ledger import (
    build_decision_ledger,
    find_decision,
    load_decision_ledger,
    write_decision_ledger,
)
from tests.hl_runtime_fakes import RuntimeFakeInfoClient, runtime_config, thin_l2, write_leader_shortlist


def test_decision_reconstructed_from_persisted_evidence(tmp_path):
    cfg = runtime_config(tmp_path)
    write_leader_shortlist(cfg)
    run = run_copy_dry_run(cfg, interval_seconds=300, network_read=True, info_client=RuntimeFakeInfoClient(l2_book=thin_l2()))
    feats = _market_features_by_coin(
        info_client=RuntimeFakeInfoClient(l2_book=thin_l2()),
        all_mids={"BTC": "50000.0"}, coins=["BTC"], l2_cache={}, candle_cache={}, source_failures=[],
    )
    entries = build_decision_ledger(run.signal_candidates, run.no_trade_decisions, feats, run_id="rebuild/1")
    assert entries
    res = write_decision_ledger(entries, cfg.reports_dir / "decision_ledger", run_id="rebuild/1")
    loaded = load_decision_ledger(res.json_path)

    # pick any decision and fully reconstruct it from the persisted ledger
    target = entries[0]
    rebuilt = find_decision(loaded, target.decision_id)
    assert rebuilt is not None
    assert rebuilt["decision_id"] == target.decision_id
    assert rebuilt["decision_type"] == target.decision_type
    assert rebuilt["evidence_hash"] == target.evidence_hash  # reproducible chain
    assert (rebuilt.get("reason_codes") or rebuilt.get("feature_hash"))  # minimal evidence
