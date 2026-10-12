"""Work/Codex bundle check: exact SHA and ordered unresolved candidate parity."""
from __future__ import annotations

import hashlib
import json

import pytest

from tools.verify_recovery_bundle import BundleError, inspect_bundle, verify_bundle, write_bundle

CATALOG = "a" * 64


def _make(tmp_path):
    head = "f" * 40
    (tmp_path / "git-head.txt").write_text(head + "\n")
    candidates = [
        {"kind": "candidate", "dataset_id": "one", "quality_status": "PARTIAL",
         "validation_allowed": False, "recovery_status": "NOT_ASSESSED"},
        {"kind": "candidate", "dataset_id": "two", "quality_status": "REJECT",
         "validation_allowed": False, "recovery_status": "NOT_ASSESSED"},
    ]
    header = {"kind": "header", "schema": "alina.recovery_triage.v1",
              "catalog_index_sha256": CATALOG, "recoverability_certified": False}
    raw_candidates = "".join(json.dumps(item, sort_keys=True) + "\n" for item in candidates).encode()
    digest = hashlib.sha256(raw_candidates).hexdigest()
    footer = {"kind": "footer", "candidate_count": 2, "candidates_sha256": digest}
    (tmp_path / "recovery-triage.jsonl").write_text(
        json.dumps(header, sort_keys=True) + "\n" +
        raw_candidates.decode() + json.dumps(footer, sort_keys=True) + "\n"
    )
    (tmp_path / "preservation-census.json").write_text(json.dumps({
        "status": "CATALOG_CLASSIFIED_NOT_RESTORED",
        "catalog_index_sha256": CATALOG,
        "all_exploitable_data_restored": False,
        "triage": {"candidate_count": 2, "candidates_sha256": digest},
    }))
    (tmp_path / "triage-verification.json").write_text(json.dumps({
        "status": "CATALOG_CLASSIFIED_NOT_RESTORED",
        "triage": {"status": "TRIAGE_VERIFIED_NOT_RESTORED", "candidate_count": 2,
                   "candidates_sha256": digest, "catalog_index_sha256": CATALOG},
    }))
    archive = b"published-archive-fixture"
    (tmp_path / "RESTORE_INVENTORY.json.gz").write_bytes(archive)
    arch_sha = hashlib.sha256(archive).hexdigest()
    (tmp_path / "published-inventory-source.json").write_text(json.dumps({
        "status": "PUBLISHED_INVENTORY_ASSET_SHA256_VERIFIED_NOT_RESTORED",
        "asset_sha256": arch_sha, "asset_size_bytes": len(archive),
        "raw_market_payloads_downloaded": 0,
    }))
    details = [{
        "dataset_id": row["dataset_id"], "quality_status": row["quality_status"],
        "validation_allowed": False, "recovery_status": "NOT_ASSESSED",
    } for row in candidates]
    raw_details = "".join(json.dumps(row, sort_keys=True) + "\n" for row in details).encode()
    (tmp_path / "source-comparison.jsonl").write_bytes(raw_details)
    (tmp_path / "source-comparison-report.json").write_text(json.dumps({
        "status": "SOURCE_SNAPSHOT_COMPARED_NOT_RESTORED",
        "catalog_index_sha256": CATALOG,
        "source_inventory_file_sha256": arch_sha,
        "source_comparison_jsonl_sha256": hashlib.sha256(raw_details).hexdigest(),
        "candidate_count": 2, "recovered_shards": None,
        "all_exploitable_data_restored": False,
    }))
    return details


def test_bundle_receipt_fully_verifies_and_never_overwrites(tmp_path):
    _make(tmp_path)
    written = write_bundle(tmp_path)
    assert written["status"] == "EVIDENCE_COMPLETE_NOT_RESTORED"
    assert written["candidate_count"] == 2
    assert written["economic_proof_allowed"] is False
    assert verify_bundle(tmp_path) == written
    with pytest.raises(BundleError, match="REFUSE_OVERWRITE"):
        write_bundle(tmp_path)


def test_bundle_detects_changed_source_and_receipt(tmp_path):
    _make(tmp_path)
    write_bundle(tmp_path)
    path = tmp_path / "source-comparison.jsonl"
    path.write_bytes(path.read_bytes().replace(b'"PARTIAL"', b'"STALE"'))
    with pytest.raises(BundleError, match="SOURCE_RECEIPT_PARITY_FAILED"):
        verify_bundle(tmp_path)
    _make(tmp_path)
    receipt = tmp_path / "WORK_RECOVERY_BUNDLE.json"
    obj = json.loads(receipt.read_text())
    obj["git_head"] = "0" * 40
    receipt.write_text(json.dumps(obj))
    with pytest.raises(BundleError, match="RECEIPT_MISMATCH"):
        verify_bundle(tmp_path)


def test_bundle_blocks_same_count_different_candidate_order(tmp_path):
    details = _make(tmp_path)
    details.reverse()
    payload = "".join(json.dumps(item, sort_keys=True) + "\n" for item in details).encode()
    (tmp_path / "source-comparison.jsonl").write_bytes(payload)
    path = tmp_path / "source-comparison-report.json"
    receipt = json.loads(path.read_text())
    receipt["source_comparison_jsonl_sha256"] = hashlib.sha256(payload).hexdigest()
    path.write_text(json.dumps(receipt))
    with pytest.raises(BundleError, match="ORDERED_IDENTITIES_DIFFER"):
        inspect_bundle(tmp_path)


def test_bundle_blocks_missing_file_and_unsafe_candidate(tmp_path):
    _make(tmp_path)
    (tmp_path / "RESTORE_INVENTORY.json.gz").unlink()
    with pytest.raises(BundleError, match="FILE_MISSING"):
        write_bundle(tmp_path)
    _make(tmp_path)
    path = tmp_path / "recovery-triage.jsonl"
    path.write_bytes(path.read_bytes().replace(b'"NOT_ASSESSED"', b'"RECOVERED"', 1))
    with pytest.raises(BundleError, match="UNSAFE_OR_DUPLICATE_CANDIDATE"):
        write_bundle(tmp_path)
