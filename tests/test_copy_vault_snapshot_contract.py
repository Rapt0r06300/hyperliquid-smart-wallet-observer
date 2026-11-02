from __future__ import annotations

from copy import deepcopy

from hl_observer.backtesting.copy_vault_snapshot_contract import (
    NOT_PROVEN,
    PROVEN,
    verify_snapshot_contract,
)


def _snapshot() -> dict[str, object]:
    digest_fields = {
        "selection_digest": "0" * 64,
        "engine_source_sha256": "1" * 64,
        "campaign_config_sha256": "2" * 64,
        "source_catalog_sha256": "3" * 64,
        "source_asset_inventory_sha256": "4" * 64,
    }
    artifacts = {
        field: {"field": field}
        for field in ("ledger", "equity", "costs", "metrics", "tests", "report")
    }
    artifacts["restoration_receipt"] = {"status": "RESTORABLE", "sha256": "7" * 64}
    return {
        "schema_version": "hypersmart.copy_vault_restoration_snapshot.v1",
        "restoration_status": "READY",
        "restoration_missing_requirements": [],
        "lineage": digest_fields | {"source_asset_inventory_count": 15456},
        "search": {
            "campaign_config": {"family": "copy_vault", "schema": "v1"},
            "proposal_seed": 0,
            "temporal_windows": {"train_start_ms": 10, "train_end_ms": 20},
            "paper_capital_usd": 200.0,
            "global_trial_count": 7,
        },
        "trial_accounting": {
            "trial_number": 7,
            "attempt_receipt_sha256": "5" * 64,
            "trial_receipt_sha256": "6" * 64,
        },
        "candidate_freeze": {
            "freeze": {"parameters": {"core_notional_usd": 20.0}, "parameters_sha256": "8" * 64},
        },
        "artifacts": artifacts,
        "artifacts_sha256": {field: "9" * 64 for field in artifacts},
        "paper_read_only": True,
        "real_execution": False,
        "restore_started": False,
        "source_untouched": True,
        "restoration_snapshot_sha256": "a" * 64,
    }


def test_complete_canonical_h95_snapshot_is_proven() -> None:
    report = verify_snapshot_contract(_snapshot())

    assert report["status"] == PROVEN
    assert report["missing"] == []
    assert report["paper_read_only"] is True
    assert report["real_execution"] is False


def test_missing_restore_artifact_is_not_filled_or_proven() -> None:
    snapshot = deepcopy(_snapshot())
    del snapshot["artifacts"]["restoration_receipt"]  # type: ignore[index]

    report = verify_snapshot_contract(snapshot)

    assert report["status"] == NOT_PROVEN
    assert "artifacts.restoration_receipt" in report["missing"]


def test_non_restorable_status_and_non_paper_mode_are_rejected() -> None:
    snapshot = deepcopy(_snapshot())
    snapshot["restoration_status"] = "UNMEASURABLE"
    snapshot["real_execution"] = True

    report = verify_snapshot_contract(snapshot)

    assert report["status"] == NOT_PROVEN
    assert "restoration_status" in report["invalid"]
    assert "real_execution" in report["invalid"]


def test_empty_source_inventory_is_not_restorable() -> None:
    snapshot = deepcopy(_snapshot())
    snapshot["lineage"]["source_asset_inventory_count"] = 0  # type: ignore[index]

    report = verify_snapshot_contract(snapshot)

    assert report["status"] == NOT_PROVEN
    assert "lineage.source_asset_inventory_count" in report["invalid"]
