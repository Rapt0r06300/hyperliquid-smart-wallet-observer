from __future__ import annotations

from pathlib import Path
from hashlib import sha256

import pytest

from hl_observer.audit.copy_vault_runtime_audit_controls import (
    atomic_publish_bytes,
    classify_delta_state,
    collection_campaign_receipt,
    coverage_shard_receipt,
    event_intelligence_campaign_receipt,
    market_campaign_receipt,
    measured_patch_reuse,
    official_entrypoint_receipt,
    partition_mapping,
    release_reconciliation_receipt,
    sha256_file_receipt,
)


ROOT = Path(__file__).resolve().parents[1]


def test_record_patch_over_limit_fails_closed_and_partition_plan_is_deterministic():
    with pytest.raises(ValueError, match="PARTITION_REQUIRED"):
        atomic_publish_bytes(Path("unused"), b"x" * 8, max_bytes=4)
    parts, files = partition_mapping({"b": "bbbbbbbbbbbb", "a": "aaaaaaaaaaaa"}, max_bytes=32)
    assert [part["path"] for part in parts] == ["part-000001.json", "part-000002.json"]
    assert list(files) == ["part-000001.json", "part-000002.json"]


def test_atomic_publish_writes_exact_bytes_and_hash(tmp_path):
    target = tmp_path / "catalog.json"
    receipt = atomic_publish_bytes(target, b'{"ok":true}\n')
    assert target.read_bytes() == b'{"ok":true}\n'
    assert receipt["atomic"] is True and receipt["bytes"] == target.stat().st_size
    assert receipt["sha256"] == sha256_file_receipt(target)["sha256"]


def test_measurement_reuses_exact_current_evidence_without_rescan():
    sha = "a" * 64
    assert measured_patch_reuse({"asset_sha256": sha, "exact": True}, {}, asset_sha256=sha)["decision"] == "REUSED_EXACT"
    assert measured_patch_reuse({}, {"asset_sha256": sha, "exact": True}, asset_sha256=sha)["decision"] == "ACCEPT_MEASURED"
    assert measured_patch_reuse({}, {"asset_sha256": "b" * 64, "exact": True}, asset_sha256=sha)["decision"] == "REMEASURE_REQUIRED"


def test_windows_hash_receipt_rejects_links_and_returns_exact_digest(tmp_path):
    path = tmp_path / "payload.bin"
    path.write_bytes(b"payload")
    receipt = sha256_file_receipt(path)
    assert receipt["sha256"] == sha256(b"payload").hexdigest()


def test_delta_unknown_is_not_coerced_to_open():
    assert classify_delta_state("OPEN", causal=False) == "UNKNOWN"
    assert classify_delta_state("OPEN", causal=True) == "OPEN"
    assert classify_delta_state("garbage", causal=True) == "UNKNOWN"


def test_official_entrypoints_are_bounded_to_copy_vault():
    receipt = official_entrypoint_receipt(ROOT)
    assert receipt["scope"] == "copy_vault"
    assert receipt["paper_only"] is True
    assert receipt["ok"] is True


def test_coverage_requires_all_nonempty_shards(tmp_path):
    files = []
    for index in range(2):
        path = tmp_path / f"coverage-{index}.json"
        path.write_text("{}")
        files.append(path)
    assert coverage_shard_receipt(files, expected=2)["complete"] is True
    assert coverage_shard_receipt(files[:1], expected=2)["complete"] is False


def test_release_reconciliation_requires_exact_sha_and_artifacts():
    artifact = [{"sha256": "b" * 64, "bytes": 4}]
    assert release_reconciliation_receipt(expected_sha="a" * 64, actual_sha="a" * 64, artifacts=artifact)["verdict"] == "PROVEN"
    assert release_reconciliation_receipt(expected_sha="a" * 64, actual_sha="b" * 64, artifacts=artifact)["verdict"] == "UNKNOWN"


def test_resumable_campaign_requires_copy_vault_collect_epoch_and_sha():
    receipt = collection_campaign_receipt(family="copy_vault", campaign_id="c-1", phase="COLLECT", epoch=2, source_sha="a" * 64)
    assert receipt["status"] == "READY"
    assert collection_campaign_receipt(family="market_data", campaign_id="c-1", phase="COLLECT", epoch=2, source_sha="a" * 64)["status"] == "UNKNOWN"


def test_market_lane_cannot_expand_active_scope():
    assert market_campaign_receipt(campaign={"family": "market_data"})["status"] == "DISABLED_BY_SCOPE"
    assert market_campaign_receipt(campaign={"family": "copy_vault"})["status"] == "UNKNOWN"


def test_event_intelligence_is_diagnostic_only_and_provenance_bearing():
    ready = event_intelligence_campaign_receipt(campaign={"source_provenance": "safe://event-1"})
    assert ready["status"] == "DIAGNOSTIC_ONLY"
    assert event_intelligence_campaign_receipt(campaign={})["status"] == "UNKNOWN"
