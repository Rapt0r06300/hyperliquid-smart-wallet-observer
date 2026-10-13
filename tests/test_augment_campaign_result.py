from __future__ import annotations

import json
from pathlib import Path

from tools.augment_campaign_result import (
    annotate_collection,
    annotate_rejected_collection,
    annotate_evidence,
    mark_durability_failure,
)


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
    assert row["sha256"] != before


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
