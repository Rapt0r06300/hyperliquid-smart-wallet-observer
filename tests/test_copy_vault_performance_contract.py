from __future__ import annotations

from copy import deepcopy

from hl_observer.backtesting.copy_vault_performance_contract import (
    NOT_PROVEN,
    PROVEN,
    validate_performance_comparison_receipt,
)


def _receipt() -> dict[str, object]:
    return {
        "schema": "hypersmart.copy_vault_performance_comparison_receipt.v1",
        "status": "COMPLETED",
        "receipt_sha256": "a" * 64,
        "paper_read_only": True,
        "real_execution": False,
        "comparison_context_sha256": "b" * 64,
        "delta_usd_per_active_day": "0.250000",
        "claims": {
            "gain_reproducible": True,
            "semantic_equivalence": True,
            "same_dataset": True,
            "same_trials": True,
            "determinism_preserved": True,
            "coverage_preserved": True,
            "data_count_preserved": True,
            "trial_count_preserved": True,
            "costs_preserved": True,
        },
        "baseline": {"receipt_sha256": "c" * 64},
        "challenger": {"receipt_sha256": "d" * 64},
    }


def test_performance_comparison_requires_explicit_same_context_claims() -> None:
    report = validate_performance_comparison_receipt(_receipt())

    assert report["status"] == PROVEN
    assert report["missing"] == []
    assert report["claims"]["semantic_equivalence"] is True
    assert report["paper_read_only"] is True


def test_performance_comparison_does_not_infer_missing_challenger() -> None:
    receipt = deepcopy(_receipt())
    del receipt["challenger"]

    report = validate_performance_comparison_receipt(receipt)

    assert report["status"] == NOT_PROVEN
    assert "challenger" in report["missing"]
    assert report["claims"] == {}


def test_performance_comparison_rejects_real_execution() -> None:
    receipt = deepcopy(_receipt())
    receipt["real_execution"] = True

    report = validate_performance_comparison_receipt(receipt)

    assert report["status"] == NOT_PROVEN
    assert "real_execution" in report["invalid"]
