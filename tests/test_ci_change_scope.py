"""Fail-closed regression checks for CI source-vs-catalog routing."""
from __future__ import annotations

import hashlib
import json

import pytest

from tools.ci_change_scope import classify_paths, verify_catalog_changes


@pytest.mark.parametrize("paths", [
    None, [], ["tools/ci_change_scope.py"], [".github/workflows/ci.yml"],
    ["catalog/metrics.json", "src/hl_observer/cli.py"],
    ["catalog/entry.py"], ["control/alina-phase.json"], ["../catalog/x.json"],
])
def test_source_or_unknown_change_always_requires_full_ci(paths):
    assert classify_paths(paths) == "source"


def test_only_plain_catalog_evidence_can_take_fast_path(tmp_path):
    rel = "catalog/campaigns/c1.json"
    target = tmp_path / rel
    target.parent.mkdir(parents=True)
    target.write_text(json.dumps({
        "paper_only": True, "read_only": True, "real_execution": False
    }), encoding="utf-8")
    assert classify_paths([rel]) == "catalog"
    verify_catalog_changes(tmp_path, [rel])


def test_catalog_only_does_not_hide_corrupt_or_live_campaign(tmp_path):
    path = tmp_path / "catalog/campaigns/unsafe.json"
    path.parent.mkdir(parents=True)
    path.write_text('{"paper_only":true,"read_only":true,"real_execution":true}')
    with pytest.raises(ValueError, match="UNSAFE_CATALOG_CAMPAIGN"):
        verify_catalog_changes(tmp_path, ["catalog/campaigns/unsafe.json"])
    path.write_text("{bad-json")
    with pytest.raises(ValueError, match="INVALID_CATALOG_JSON"):
        verify_catalog_changes(tmp_path, ["catalog/campaigns/unsafe.json"])


def test_health_receipt_requires_real_digest(tmp_path):
    path = tmp_path / "catalog/DATASET_HEALTH_RECEIPT.json"
    path.parent.mkdir(parents=True)
    body = {"schema_version": "alina.dataset_health_receipt.v2", "paper_only": True}
    body["receipt_digest"] = hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()
    path.write_text(json.dumps(body), encoding="utf-8")
    verify_catalog_changes(tmp_path, ["catalog/DATASET_HEALTH_RECEIPT.json"])
    body["paper_only"] = False
    path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError, match="DATASET_HEALTH_DIGEST_MISMATCH"):
        verify_catalog_changes(tmp_path, ["catalog/DATASET_HEALTH_RECEIPT.json"])


def test_never_hide_deletion_of_critical_catalog(tmp_path):
    with pytest.raises(ValueError, match="CRITICAL_CATALOG_FILE_MISSING"):
        verify_catalog_changes(tmp_path, ["catalog/DATA_INDEX.json"])

def test_catalog_only_rejects_corrupt_jsonl(tmp_path):
    target = tmp_path / "catalog/receipts/rows.jsonl"
    target.parent.mkdir(parents=True)
    target.write_text('{"valid": 1}\n{broken}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="INVALID_CATALOG_JSONL"):
        verify_catalog_changes(tmp_path, ["catalog/receipts/rows.jsonl"])
