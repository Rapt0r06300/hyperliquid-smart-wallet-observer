from __future__ import annotations

from copy import deepcopy

from tools.build_copy_vault_restoration_evidence import build_evidence


def _report() -> dict[str, object]:
    return {
        "schema": "alina.full_restore_report.v1",
        "status": "REPLAY_READY_COMPLETE",
        "read_only": True,
        "real_execution": False,
        "restore_complete": True,
        "replay_ready_complete": True,
        "all_source_assets_accounted_for": True,
        "source_byte_parity": True,
        "source_destination_match": True,
        "verification_failures": 0,
        "unverified_source_asset_count": 0,
        "failed_verification_source_bytes": 0,
        "missing_asset_bytes": 0,
        "source_inventory_sha256": "a" * 64,
        "verified_asset_count": 10,
        "verified_asset_bytes": 100,
        "restored_volume_bytes": 100,
    }


def test_real_restore_report_becomes_verified_evidence() -> None:
    result = build_evidence(
        _report(),
        source_report_sha256="b" * 64,
        head_sha="c" * 40,
        source="RESTORE_REPORT.json",
    )

    assert result["evidence_status"] == "VERIFIED"
    assert result["real_execution"] is False
    assert result["claims"]["restore_verified"] is True
    assert result["claims"]["replayed_sha256_match"] is True
    assert result["unresolved"] == []
    assert result["run_id"] == f"restore-report:{'b' * 64}"


def test_missing_restore_parity_fails_closed_without_claims() -> None:
    report = deepcopy(_report())
    report["source_destination_match"] = False

    result = build_evidence(
        report,
        source_report_sha256="b" * 64,
        head_sha="c" * 40,
        source="RESTORE_REPORT.json",
    )

    assert result["evidence_status"] == "NOT_PROVEN"
    assert result["claims"] == {
        "restore_verified": False,
        "replayed_sha256_match": False,
        "restoration_receipt_present": False,
        "source_report_untouched": False,
    }
    assert "source_destination_match" in result["unresolved"]
