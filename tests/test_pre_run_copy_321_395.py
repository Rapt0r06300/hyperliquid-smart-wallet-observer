from __future__ import annotations

import hashlib
from pathlib import Path

from hl_observer.backtesting.copy_vault_generalization import derive_heldout_vault_generalization
from hl_observer.ops.pre_run_copy_321_395 import COPY_REQUIREMENTS, FACETS, evaluate_copy_requirements
from hl_observer.simulation.copy_campaign_adapter import build_strict_copy_campaign

ROOT = Path(__file__).resolve().parents[1]


def _strict_trade(index: int, *, vault: str, ts_ms: int, net: float = 1.0, tamper: bool = False) -> dict:
    fees, spread, slippage, latency = .05, .04, .01, .02
    gross = net + fees + spread + slippage + latency + (1.0 if tamper else 0.0)
    return {"trade_id": hashlib.sha256(f"{index}-{vault}-{ts_ms}".encode()).hexdigest(), "vault": vault, "coin": "BTC",
            "direction": 1, "signal_ts_ms": ts_ms, "entry_ts_ms": ts_ms + 60_000, "exit_ts_ms": ts_ms + 360_000,
            "reference_lag_ms": 0, "entry_target_lag_ms": 0, "exit_target_lag_ms": 0, "observed_latency_ms": 60_000,
            "notional_usd": 150.0, "entry_capacity_usd": 300.0, "exit_capacity_usd": 300.0,
            "gross_pnl_usd": gross, "fees_usd": fees, "spread_cost_usd": spread, "slippage_cost_usd": slippage,
            "latency_cost_usd": latency, "net_pnl_usd": net, "liquidatable_net": True, "paper_read_only": True,
            "real_execution": False, "causal_books_eligible": True, "causal_forward_eligible": True}


def test_copy_registry_executes_15_requirements_and_75_specific_facets() -> None:
    result = evaluate_copy_requirements(ROOT)
    assert len(COPY_REQUIREMENTS) == 15
    assert len(FACETS) == 5
    assert result["requirements_total"] == 15
    assert result["requirements_done"] == 15, result
    assert result["facets_total"] == 75
    assert result["facets_done"] == 75
    assert result["ok"] is True


def test_every_copy_requirement_has_distinct_executable_result_and_hashed_evidence() -> None:
    result = evaluate_copy_requirements(ROOT)
    assert [row["key"] for row in result["requirements"]] == [key for key, _ in COPY_REQUIREMENTS]
    for row in result["requirements"]:
        assert all(row["facets"].values()), row
        assert row["evidence"]
        assert set(row["evidence_sha256"]) == set(row["evidence"])
        for digest in row["evidence_sha256"].values():
            assert len(digest) == 64
            int(digest, 16)


def test_strict_heldout_excludes_seen_vault_and_rejects_cost_tampering() -> None:
    rows = [_strict_trade(1, vault="0xA", ts_ms=100), _strict_trade(2, vault="0xA", ts_ms=300), _strict_trade(3, vault="0xB", ts_ms=300)]
    proof = derive_heldout_vault_generalization(rows, oos_start_ms=200)
    assert proof is not None
    assert proof["vaults_held_out"] == ["0xb"]
    assert proof["sample_count"] == 1
    assert proof["economic_claim_eligible"] is True
    assert proof["net_bps"] is not None
    bad = derive_heldout_vault_generalization([_strict_trade(4, vault="0xC", ts_ms=300, tamper=True)], oos_start_ms=200)
    assert bad is not None
    assert bad["economic_claim_eligible"] is False
    assert bad["net_bps"] is None
    assert bad["rejection_reasons"]["ECONOMIC_RECONCILIATION_FAILED"] == 1


def test_strict_heldout_rejects_duplicate_trade_identity() -> None:
    first = _strict_trade(10, vault="0xB", ts_ms=300)
    proof = derive_heldout_vault_generalization([first, dict(first)], oos_start_ms=200)
    assert proof is not None
    assert proof["sample_count"] == 1
    assert proof["duplicate_trade_ids"] == 1
    assert proof["economic_claim_eligible"] is False
    assert proof["net_bps"] is None


def _segment(net: float, char: str) -> dict:
    return {"gross_pnl_usd": net + .4, "fees_usd": .1, "spread_cost_usd": .1, "slippage_cost_usd": .1,
            "latency_cost_usd": .1, "net_pnl_usd": net, "sample_count": 1, "liquidatable_net": True,
            "duplicate_trade_ids": 0, "trade_ids_count": 1, "trade_ids_sha256": char * 64}


def _executable_report() -> dict:
    return {"schema_version": "hypersmart.copy_vault_executable_campaign.v1",
            "summary": {"positions_ouvertes": 2, "positions_fermees": 2, "gross_pnl_usd": 5.8, "fees_usd": .4,
                        "spread_cost_usd": .4, "slippage_cost_usd": .1, "latency_cost_usd": .1, "net_pnl_usd": 4.8,
                        "roi_pct": .48, "max_drawdown_usd": .2, "hit_rate": 1.0, "profit_factor": None,
                        "LIQUIDATABLE_NET": True, "duplicate_trade_ids": 0, "trade_ids_count": 2, "trade_ids_sha256": "a" * 64},
            "temporal_evidence": {"oos": {**_segment(2.2, "b"), "no_lookahead": True},
                                  "forward": {**_segment(2.6, "c"), "post_freeze": True}, "placebos": {"beaten": True}},
            "vault_generalization": {"sample_count": 20, "net_bps": 3.0, "economic_claim_eligible": True,
                                     "duplicate_trade_ids": 0, "rejected_candidate_count": 0, "proof_mode": "STRICT_EXECUTABLE"},
            "metaorder_audit": {"metaorders": 20}, "calibration": {"status": "TRAIN_SELECTED"},
            "params": {"selection_status": "TRAIN_SELECTED"}}


def test_adapter_preserves_executable_strict_heldout_proof() -> None:
    campaign = build_strict_copy_campaign(_executable_report(), freeze={"campaign_id": "x", "frozen_at_ms": 1000,
        "selected_before_final_evaluation": True}, datasets={"files": []})
    assert campaign["vault_generalization"]["proof_mode"] == "STRICT_EXECUTABLE"
    assert campaign["vault_generalization"]["economic_claim_eligible"] is True


def test_legacy_vault_split_is_diagnostic_only_and_cannot_promote_copy() -> None:
    legacy = {"mesure": {"generalisation_par_vault": {"n": 100, "net_bps": 99.0, "vaults_held_out": ["0xfake"]}}}
    campaign = build_strict_copy_campaign(legacy, freeze={"campaign_id": "x", "frozen_at_ms": 1000,
        "selected_before_final_evaluation": True}, datasets={"files": []})
    assert campaign["vault_generalization"] is None
    assert campaign["legacy_vault_generalization_diagnostic"]["economic_claim_eligible"] is False
    assert "COPY_HELDOUT_VAULT_PROOF_MISSING" in campaign["objective_reasons"]
