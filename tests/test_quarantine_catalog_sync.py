"""A quarantine snapshot may never outlive or disagree with its source index."""
from __future__ import annotations

import hashlib
import json

import pytest

from tools.build_replay_compatibility_reasons import build_quarantine_report


def _fixture():
    rows = [
        {"dataset_id": "safe", "quality_status": "SAFE", "record_count": 4,
         "venue": "binance", "family": "trades"},
        {"dataset_id": "partial", "quality_status": "PARTIAL", "record_count": 9,
         "venue": "gate", "family": "trades"},
        {"dataset_id": "reject", "quality_status": "REJECT", "record_count": 12,
         "venue": "okx", "family": "l2Book"},
    ]
    classifications = [
        {"dataset_id": "safe", "reason_code": "SAFE_REPLAY_COMPATIBLE",
         "blocking_reasons": []},
        {"dataset_id": "partial", "reason_code": "REPLAY_COMPATIBILITY_NOT_PROVEN",
         "blocking_reasons": ["RECONCILIATION_UNVERIFIED"]},
        {"dataset_id": "reject", "reason_code": "FATAL_INTEGRITY:gap_count=1",
         "blocking_reasons": ["FATAL_INTEGRITY:gap_count=1"]},
    ]
    digest = hashlib.sha256(json.dumps(rows).encode()).hexdigest()
    metrics = {
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": digest,
        "totals": {"TOTAL_SHARDS": 3, "SAFE_SHARDS": 1,
                   "PARTIAL_SHARDS": 1, "REJECTED_SHARDS": 1},
    }
    return rows, classifications, digest, metrics


def test_quarantine_matches_sha_bound_current_catalog():
    rows, classifications, digest, metrics = _fixture()
    result = build_quarantine_report(rows, classifications, metrics, digest)
    assert result["source_index_sha256"] == digest
    assert result["source_shards"] == 3
    assert result["non_safe_shards"] == 2
    assert result["by_status"]["PARTIAL"]["records"] == 9
    assert result["by_status"]["REJECT"]["shards"] == 1
    assert result["current_reasons"]["RECONCILIATION_UNVERIFIED"]["records"] == 9
    assert result["quarantine_total_matches_metrics"] is True
    assert "SAFE" not in result["by_status"]


@pytest.mark.parametrize("mutation", ["stale_sha", "stale_count", "wrong_status"])
def test_quarantine_fails_closed_on_stale_or_conflicting_metrics(mutation):
    rows, classifications, digest, metrics = _fixture()
    if mutation == "stale_sha":
        metrics["source_index_sha256"] = "0" * 64
    elif mutation == "stale_count":
        metrics["totals"]["TOTAL_SHARDS"] = 2
    else:
        metrics["totals"]["PARTIAL_SHARDS"] = 2
    with pytest.raises(ValueError, match="QUARANTINE_"):
        build_quarantine_report(rows, classifications, metrics, digest)


def test_quarantine_fails_on_duplicate_dataset_identity():
    rows, classifications, digest, metrics = _fixture()
    rows[1]["dataset_id"] = "safe"
    classifications[1]["dataset_id"] = "safe"
    with pytest.raises(ValueError, match="AMBIGUOUS_IDENTITY"):
        build_quarantine_report(rows, classifications, metrics, digest)


def test_quarantine_reports_incomplete_records_without_claiming_zero():
    rows, classifications, digest, metrics = _fixture()
    rows[1].pop("record_count")
    result = build_quarantine_report(rows, classifications, metrics, digest)
    assert result["record_counts_complete"] is False
    assert result["record_count_unavailable_shards"] == 1
    assert result["non_safe_shards"] == 2
