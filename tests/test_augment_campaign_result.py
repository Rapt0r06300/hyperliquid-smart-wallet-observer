from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.augment_campaign_result import (
    annotate_collection,
    annotate_rejected_collection,
    annotate_evidence,
    mark_durability_failure,
)
from tools.copy_vault_continuity import load_release_history_audits


def _result(path: Path) -> None:
    path.write_text(
        json.dumps({
            "status":"COMPLETE",
            "sha256":"0"*64,
            "payload":{"status":"COMPLETE"},
            "progressed":True,
        }),
        encoding="utf-8",
    )


def test_collection_annotation_rehashes_and_persists_counts(tmp_path):
    result=tmp_path/"result.json"
    manifest=tmp_path/"RUN_MANIFEST.json"
    _result(result)
    manifest.write_text(
        json.dumps({
            "shard_count":4,
            "safe_count":2,
            "partial_count":1,
            "reject_count":1,
            "source_admission":{"excluded_shards":3,"no_rejected_payload_published":True},
        }),
        encoding="utf-8",
    )
    before=json.loads(result.read_text())["sha256"]
    row=annotate_collection(
        result,
        manifest,
        tag="data-v2-campaign-test",
        repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
    )
    assert row["payload"]["durable_persisted"] is True
    assert row["payload"]["safe_count"] == 2
    assert row["payload"]["source_admission"]["excluded_shards"] == 3
    assert row["sha256"] != before


def test_collection_annotation_preserves_structured_historical_backfill_audit(tmp_path):
    result = tmp_path / "result.json"
    manifest = tmp_path / "RUN_MANIFEST.json"
    _result(result)
    reports = {
        "0x" + "a" * 40: {
            "status": "COMPLETE",
            "request_audit_status": "COMPLETE",
            "checkpoint_advance_allowed": True,
            "retention_cap_reached": False,
            "requested_start_ms": 1_000,
            "requested_end_ms": 2_000,
            "rows": 3,
            "pending_windows": 0,
            "request_budget_exhausted": False,
            "invalid_fill_count": 0,
            "failed_windows": [],
            "cap_blocked_windows": [],
            "unresolved_gaps": [],
        }
    }
    reports_json = json.dumps(
        reports, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    audit = {
        "schema": "alina.copy_vault.historical_backfill_audit.v1",
        "source": "BUNDLE_INDEX.json",
        "status": "COMPLETE",
        "report_count": 1,
        "reports_sha256": hashlib.sha256(reports_json).hexdigest(),
        "reports_bytes": len(reports_json),
        "reports": reports,
    }
    row = json.loads(result.read_text(encoding="utf-8"))
    row["payload"]["collection_metrics"] = {
        "started_at_ms": 1_000,
        "historical_backfill_audit": audit,
    }
    result.write_text(json.dumps(row), encoding="utf-8")
    manifest.write_text(
        json.dumps({
            "shard_count": 1,
            "safe_count": 1,
            "partial_count": 0,
            "reject_count": 0,
            "manifests": [],
        }),
        encoding="utf-8",
    )

    annotated = annotate_collection(
        result,
        manifest,
        tag="data-v2-campaign-test",
        repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
    )

    metrics = annotated["payload"]["collection_metrics"]
    assert metrics["historical_backfill_audit"] == audit
    assert metrics["started_at_ms"] == 1_000
    assert metrics["basis"] == "published_run_manifest"
    receipt = tmp_path / "copy-vault-campaign-test.json"
    receipt.write_text(json.dumps({
        "kind": "copy_vault_collection",
        "status": "COMPLETE",
        "completed_units": {
            "0": {
                "result": annotated["payload"],
                "sha256": annotated["sha256"],
            }
        },
    }), encoding="utf-8")
    loaded = load_release_history_audits(
        tmp_path,
        release_tags={"data-v2-campaign-test"},
    )
    assert loaded["status"] == "COMPLETE"
    assert loaded["audited_release_count"] == 1


def test_evidence_annotation_is_durable(tmp_path):
    result=tmp_path/"result.json"
    _result(result)
    row=annotate_evidence(
        result,
        tag="campaign-evidence-test",
        repository="Rapt0r06300/hyperliquid-smart-wallet-observer",
    )
    assert row["payload"]["evidence_release_tag"]=="campaign-evidence-test"
    assert row["payload"]["durable_persisted"] is True


def test_durability_failure_never_keeps_complete(tmp_path):
    result=tmp_path/"result.json"
    _result(result)
    row=mark_durability_failure(result)
    assert row["status"]=="FAILED"
    assert row["progressed"] is False
    assert row["payload"]["failure_category"]=="INFRASTRUCTURE"

def test_durability_failure_preserves_bounded_publication_detail(tmp_path):
    result=tmp_path/"result.json"
    detail=tmp_path/"publish-error.txt"
    _result(result)
    detail.write_text(
        "gh release create failed: HTTP 403 secondary rate limit exceeded\n",
        encoding="utf-8",
    )
    row=mark_durability_failure(result,detail_path=detail)
    assert row["payload"]["reason"]=="durable_publication_failed"
    assert "HTTP 403" in row["payload"]["publication_error_detail"]
    assert len(row["payload"]["publication_error_detail"]) <= 2000



def test_zero_viable_result_is_durable_partial_without_phantom_release(tmp_path):
    result = tmp_path / "result.json"
    diagnostic = tmp_path / "diagnostic.json"
    _result(result)
    diagnostic.write_text(json.dumps({
        "schema": "alina.dataset_publication_skipped.v1",
        "status": "NO_REPLAY_ADMISSIBLE_SHARDS",
        "excluded_payload_count": 7,
        "source_admission": {"excluded_shards": 7},
        "read_only": True, "real_execution": False,
    }))
    row = annotate_rejected_collection(result, diagnostic)
    assert row["status"] == "PARTIAL"
    assert row["progressed"] is False
    assert row["payload"]["release_tag"] is None
    assert row["payload"]["excluded_payload_count"] == 7
    assert row["payload"]["durable_persisted"] is False
    assert len(row["sha256"]) == 64
    assert json.loads(result.read_text()) == row


def test_zero_viable_receipt_cannot_claim_real_execution(tmp_path):
    import pytest
    result = tmp_path / "result.json"
    diagnostic = tmp_path / "diagnostic.json"
    _result(result)
    diagnostic.write_text(json.dumps({
        "schema": "alina.dataset_publication_skipped.v1",
        "status": "NO_REPLAY_ADMISSIBLE_SHARDS",
        "excluded_payload_count": 1,
        "read_only": True, "real_execution": True,
    }))
    with pytest.raises(ValueError, match="INVALID_ZERO_VIABLE"):
        annotate_rejected_collection(result, diagnostic)
    assert json.loads(result.read_text())["status"] == "COMPLETE"
