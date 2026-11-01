from __future__ import annotations

from src.hl_observer.backtesting.copy_vault_causal_evidence_contract import (
    NOT_PROVEN,
    PROVEN,
    validate_l4_pairing_receipt,
    validate_live_ws_causal_receipt,
)


def _common(schema: str) -> dict[str, object]:
    return {
        "schema": schema,
        "completed": True,
        "receipt_sha256": "a" * 64,
        "paper_read_only": True,
        "real_execution": False,
        "claims": {
            "point_in_time": True,
            "provenance_by_provider_coin": True,
            "timestamps_present": True,
            "error_rates_present": True,
        },
    }


def test_l4_pairing_requires_real_safe_inputs_and_reports_claims() -> None:
    receipt = _common("hypersmart.copy_vault_l4_pairing_receipt.v1")
    receipt["claims"] = {
        **receipt["claims"],
        "real_l4_session": True,
        "paired_public_fills": True,
        "paired_safe_l2": True,
        "incremental_value": True,
        "causal_coverage": 1,
    }

    result = validate_l4_pairing_receipt(receipt)

    assert result["status"] == PROVEN
    assert result["task_id"] == "H-T115"


def test_l4_pairing_refuses_fixture_or_missing_coverage() -> None:
    receipt = _common("hypersmart.copy_vault_l4_pairing_receipt.v1")
    receipt["claims"] = {
        **receipt["claims"],
        "real_l4_session": False,
        "paired_public_fills": True,
        "paired_safe_l2": True,
        "incremental_value": True,
    }

    result = validate_l4_pairing_receipt(receipt)

    assert result["status"] == NOT_PROVEN
    assert "CLAIM_MISMATCH:real_l4_session" in result["missing_evidence"]
    assert "CLAIM_MISSING:causal_coverage" in result["missing_evidence"]


def test_live_ws_requires_post_ack_causal_fill_and_anti_double_count() -> None:
    receipt = _common("hypersmart.copy_vault_live_ws_causal_receipt.v1")
    receipt["claims"] = {
        **receipt["claims"],
        "causal_live_fill_rows": 1,
        "post_ack": True,
        "cutoff_epoch_present": True,
        "anti_double_count": True,
        "native_identity_reconciled": True,
        "snapshot_excluded_from_forward": True,
        "live_ws_provenance": True,
    }

    result = validate_live_ws_causal_receipt(receipt)

    assert result["status"] == PROVEN
    assert result["task_id"] == "H-T170"


def test_live_ws_refuses_snapshot_or_non_causal_rows() -> None:
    receipt = _common("hypersmart.copy_vault_live_ws_causal_receipt.v1")
    receipt["claims"] = {
        **receipt["claims"],
        "causal_live_fill_rows": 0,
        "post_ack": False,
        "cutoff_epoch_present": True,
        "anti_double_count": True,
        "native_identity_reconciled": True,
        "snapshot_excluded_from_forward": False,
        "live_ws_provenance": True,
    }

    result = validate_live_ws_causal_receipt(receipt)

    assert result["status"] == NOT_PROVEN
    assert "CLAIM_MISMATCH:causal_live_fill_rows" in result["missing_evidence"]
    assert "CLAIM_MISMATCH:post_ack" in result["missing_evidence"]
    assert "CLAIM_MISMATCH:snapshot_excluded_from_forward" in result["missing_evidence"]
