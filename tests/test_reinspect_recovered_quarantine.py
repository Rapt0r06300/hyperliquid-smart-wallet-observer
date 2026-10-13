"""Replay reinspection of SHA-bound quarantined shards: never auto-SAFE."""
from __future__ import annotations

import gzip
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from tools import recover_one_quarantined_shard as recover
from tools import reinspect_recovered_quarantine as check


def _fixture(tmp_path, monkeypatch, payload=None):
    if payload is None:
        payload = b'{"timestamp_ms":1000,"source_id":"fixture"}\n'
    logical = gzip.compress(payload)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr("shard.jsonl.gz", logical)
    outer = archive.getvalue()
    row = {
        "dataset_id": "demo", "quality_status": "PARTIAL", "family": "bbo",
        "venue": "gate", "symbol": "BTC", "release_tag": "fixture-tag",
        "release_asset": "shard.jsonl.gz", "release_container_asset": "bundle.zip",
        "release_remote_size": len(outer),
        "release_remote_digest": "sha256:" + hashlib.sha256(outer).hexdigest(),
        "sha256": hashlib.sha256(logical).hexdigest(), "bytes": len(logical),
        "manifest_path": "datasets/quarantine/demo.manifest.json",
        "replay_compatible": False,
    }
    root = tmp_path / "repo"
    root.mkdir()
    manifest_path = root / row["manifest_path"]
    manifest_path.parent.mkdir(parents=True)
    manifest = {
        "dataset_id": "demo", "quality_status": "PARTIAL", "family": "bbo",
        "venue": "gate", "symbol": "BTC", "sha256": row["sha256"],
        "bytes": row["bytes"], "integrity": {"gap_count": 0},
    }
    manifest_path.write_text(json.dumps(manifest))
    index = {"release_repository_default": recover.CANONICAL, "shards": [row]}
    candidate = recover.candidate_from_index(index, "demo")
    asset = {
        "id": 123, "size": len(outer),
        "digest": "sha256:" + candidate["outer_sha256"],
        "browser_download_url": "https://example.invalid/test",
    }
    recovered_root = tmp_path / "quarantine-recovery"
    recovered_root.mkdir()
    def write_bytes(_url, target, **kwargs):
        target.write_bytes(outer)
        return len(outer), hashlib.sha256(outer).hexdigest()
    monkeypatch.setattr(recover, "_download_to_path", write_bytes)
    restored = recover.hydrate_candidate(
        candidate, asset, recovered_root,
        download=True, catalog_index_sha256="f" * 64,
        max_source_bytes=1_000_000,
    )
    return index, recovered_root, root, manifest_path, restored


def test_verified_recovery_content_is_measured_without_safe_promotion(tmp_path, monkeypatch):
    index, output, repo, manifest, restore = _fixture(tmp_path, monkeypatch)
    report = check.reinspect(index, "f" * 64, output, "demo", repo_root=repo)
    assert report["status"] == "CONTENT_REPLAY_CHECK_PASSED_NOT_SAFE"
    assert report["inspection"]["record_count"] == 1
    assert report["inspection"]["invalid_record_count"] == 0
    assert report["isolated_parse_chronology_compatible"] is True
    assert report["byte_coverage_verified"] is True
    assert report["validation_allowed"] is False
    assert report["replay_certified"] is False
    assert report["reclassified_safe"] is False
    assert report["cross_shard_continuity_proven"] is False
    assert restore["quarantine_file"]
    assert json.loads(manifest.read_text())["quality_status"] == "PARTIAL"
    assert index["shards"][0]["quality_status"] == "PARTIAL"


def test_corrupt_or_missing_cached_byte_proof_fails_closed(tmp_path, monkeypatch):
    index, output, repo, _manifest, restore = _fixture(tmp_path, monkeypatch)
    target = output / restore["quarantine_file"]
    original = target.read_bytes()
    target.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="QUARANTINE_BYTES_NOT_VERIFIED"):
        check.reinspect(index, "f" * 64, output, "demo", repo_root=repo)
    assert target.read_bytes() == b"tampered"
    target.write_bytes(original)
    assert check.reinspect(index, "f" * 64, output, "demo", repo_root=repo)["byte_coverage_verified"]


def test_unbounded_gzip_and_invalid_jsonl_never_claim_safe(tmp_path, monkeypatch):
    large_payload = b'{"timestamp_ms":1000}\n' * 300
    index, output, repo, _, _ = _fixture(tmp_path, monkeypatch, large_payload)
    with pytest.raises(ValueError, match="UNCOMPRESSED_SIZE_BUDGET_EXCEEDED"):
        check.reinspect(index, "f" * 64, output, "demo", repo_root=repo,
                        max_uncompressed_bytes=100)
    other = tmp_path / "other"
    other.mkdir()
    broken, dest, reporoot, _, _ = _fixture(other, monkeypatch, b"not-json\n")
    result = check.reinspect(broken, "f" * 64, dest, "demo", repo_root=reporoot)
    assert result["status"] == "CONTENT_REPLAY_CHECK_FAILED_NOT_SAFE"
    assert result["inspection"]["invalid_record_count"] > 0
    assert result["replay_certified"] is False


def test_manifest_sha_conflict_refused_before_parsing(tmp_path, monkeypatch):
    index, output, repo, manifest_path, _ = _fixture(tmp_path, monkeypatch)
    manifest = json.loads(manifest_path.read_text())
    manifest["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="MANIFEST_CATALOG_IDENTITY_MISMATCH"):
        check.reinspect(index, "f" * 64, output, "demo", repo_root=repo)


def test_sparse_checkout_reads_original_manifest_from_git_object(tmp_path, monkeypatch):
    index, output, repo, manifest_path, _ = _fixture(tmp_path, monkeypatch)
    expected = manifest_path.read_bytes()
    manifest_path.unlink()
    calls = []
    def fake_git(command, **_kwargs):
        calls.append(command)
        if "cat-file" in command:
            return SimpleNamespace(returncode=0, stdout=str(len(expected)))
        return SimpleNamespace(returncode=0, stdout=expected)
    monkeypatch.setattr(check.subprocess, "run", fake_git)
    report = check.reinspect(index, "f" * 64, output, "demo", repo_root=repo)
    assert report["status"] == "CONTENT_REPLAY_CHECK_PASSED_NOT_SAFE"
    assert any("cat-file" in c for c in calls)
    assert any("show" in c for c in calls)
    assert not manifest_path.exists()


def test_manifest_global_drop_counter_does_not_override_event_gap_or_promote(tmp_path, monkeypatch):
    payload = (b'{"timestamp_ms":1000,"source_id":"fixture","gap_count":0,'
               b'"exchange_ts_ms":1000,"received_ts_ms":4600000,'
               b'"parsed_summary":{"action":"snapshot"}}\n')
    index, cache, repo, manifest_path, _ = _fixture(tmp_path, monkeypatch, payload)
    manifest = json.loads(manifest_path.read_text())
    manifest["integrity"]["gap_count"] = 961
    manifest["collection_queue_drops"] = 961
    manifest["reconciliation"] = {"status": "PARTIAL", "missing_from_live": 1}
    manifest_path.write_text(json.dumps(manifest))
    receipt = check.reinspect(index, "f" * 64, cache, "demo", repo_root=repo)
    assert receipt["manifest_integrity_gap_count"] == 961
    assert receipt["manifest_collection_queue_drops"] == 961
    assert receipt["observed_event_gap_signals"]["explicit_event_gap_total"] == 0
    assert receipt["observed_event_gap_signals"]["explicit_event_gap_marker_rows"] == 1
    assert receipt["observed_event_gap_signals"]["reported_snapshot_rows"] == 1
    assert receipt["manifest_gap_exceeds_explicit_event_markers"] is True
    assert receipt["gap_provenance_reconciled"] is False
    assert receipt["manifest_reference_trades_missing_from_live"] == 1
    assert receipt["reference_trade_deficit_repaired"] is False
    ages = receipt["observed_event_gap_signals"]
    assert ages["exchange_to_receive_count"] == 1
    assert ages["exchange_to_receive_max_ms"] == 4599000
    assert ages["exchange_to_receive_over_1000ms"] == 1
    assert ages["exchange_to_receive_over_10000ms"] == 1
    assert ages["executable_event_time_freshness_certified"] is False
    assert receipt["event_time_freshness_certified"] is False
    assert receipt["status"] == "CONTENT_REPLAY_CHECK_FAILED_NOT_SAFE"
    assert receipt["reclassified_safe"] is False
    assert receipt["validation_allowed"] is False
