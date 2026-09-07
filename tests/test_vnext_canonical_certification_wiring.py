from __future__ import annotations

from hl_observer.ops import final_economic_certification as certification


def _otherwise_certifiable_vnext_payload() -> dict[str, object]:
    return {
        "family": "lead_lag",
        "economic_contract": {},
        "assumption_snapshot_hash": "a" * 64,
        "objective_status": "ATTEINT",
        "eligible_net_pnl_usd": 4.5,
        "fees_usd": 0.1,
        "spread_cost_usd": 0.1,
        "slippage_cost_usd": 0.1,
        "latency_cost_usd": 0.1,
        "liquidatable_net": True,
        "dataset_provenance": {"dataset_fingerprint": "d" * 64},
        "parameter_freeze": {
            "campaign_id": "freeze-lead-lag",
            "frozen_at_ms": 1_000,
            "selected_before_final_evaluation": True,
            "parameters_sha256": "e" * 64,
        },
        "oos": {"net_pnl_usd": 2.1},
        "forward": {"net_pnl_usd": 2.1, "post_freeze": True},
        "placebos": {"beaten": True},
        "vnext_promotion": {
            "certification_status": "TRAIN_ONLY_NOT_CERTIFIED",
            "paper_read_only": True,
            "real_execution": False,
        },
    }


def test_canonical_certification_rejects_train_only_vnext_candidate(monkeypatch) -> None:
    monkeypatch.setattr(
        certification,
        "audit_economic_contract_receipt",
        lambda *_args, **_kwargs: {
            "ready": True,
            "issues": [],
            "assumption_snapshot_hash": "a" * 64,
        },
    )
    monkeypatch.setattr(
        certification,
        "evaluate_objective",
        lambda _payload: {
            "objective_status": "ATTEINT",
            "eligible_net_pnl_usd": 4.5,
            "proof_net_pnl_usd": 4.5,
            "objective_reasons": [],
        },
    )

    result = certification.certify_campaign(
        "lead_lag", _otherwise_certifiable_vnext_payload()
    )

    assert result["certified"] is False
    assert "VNEXT_PROMOTION_NOT_CERTIFIED" in result["reasons"]
