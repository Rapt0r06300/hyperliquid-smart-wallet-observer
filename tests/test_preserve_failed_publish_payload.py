"""Bounded, fail-closed cloud-only recovery of eligible unpublished shards."""
import gzip
import hashlib
import json
import tarfile

import pytest

from tools import preserve_failed_publish_payload as module


def make_bundle(tmp_path):
    root = tmp_path / "bundle"
    (root / "assets").mkdir(parents=True)
    (root / "manifests").mkdir()
    raw = gzip.compress(b'{"event_ts_ms":1000}\n')
    safe_sha = hashlib.sha256(raw).hexdigest()

    def manifest(dataset_id, filename, quality, reasons, compatible):
        return {
            "dataset_id": dataset_id,
            "family": "l2Book", "venue": "bybit", "symbol": "BTCUSDT",
            "start_ts_ms": 1000, "end_ts_ms": 1001,
            "sha256": safe_sha, "bytes": len(raw), "event_count": 1,
            "collector_version": "b" * 40, "source": "bybit_public_ws",
            "quality_status": quality, "quality_reasons": reasons,
            "release_asset": filename, "asset_verified": False,
            "replay_compatible": compatible,
            "provenance": {"public_data_only": True, "authenticated": False,
                           "real_execution": False, "transports": ["websocket"]},
            "integrity": {"gap_count": 0, "duplicate_count": 0,
                          "regression_count": 0, "missing_timestamp_count": 0,
                          "missing_monotonic_count": 0, "desync_count": 0,
                          "duplicates_deduped": True},
            "synchronization": {"connection_count": 1},
            "reconciliation": {"status": "SOURCE_CONTINUITY_VERIFIED"},
            "required_channels": [], "observed_channels": ["l2Book"],
            "cost_model": {"applicable": False, "ready": False},
        }

    included = manifest(
        "pending-remote", "safe.jsonl.gz", "PARTIAL",
        ["REMOTE_ASSET_NOT_VERIFIED"], True,
    )
    excluded = manifest(
        "fatal-gap", "bad.jsonl.gz", "REJECT", ["SEQUENCE_OR_QUEUE_GAP"], False,
    )
    for filename, row in (("safe", included), ("bad", excluded)):
        (root / "assets" / row["release_asset"]).write_bytes(raw)
        (root / "manifests" / (filename + ".json")).write_text(
            json.dumps(row), encoding="utf-8"
        )
    (root / "BUNDLE_INDEX.json").write_text(json.dumps({
        "schema": "alina.dataset_bundle.v2",
        "manifests": ["manifests/safe.json", "manifests/bad.json"],
        "assets": ["assets/safe.jsonl.gz", "assets/bad.jsonl.gz"],
        "shard_count": 2, "safe_count": 0, "partial_count": 1, "reject_count": 1,
    }), encoding="utf-8")
    result = tmp_path / "result.json"
    result.write_text(json.dumps({
        "status": "COMPLETE", "payload": {"bundle_root": str(root)}
    }), encoding="utf-8")
    return root, result


def test_failed_publish_fallback_keeps_only_publisher_admissible_shards(tmp_path):
    root, result = make_bundle(tmp_path)
    archive_path = tmp_path / "failed-quarantine.tgz"
    report = module.preserve(result, archive_path)
    assert report["status"] == "QUARANTINE_ARCHIVED"
    assert report["candidate_shards"] == 1
    assert report["excluded"] == 1
    assert report["replay_certified"] is False
    assert hashlib.sha256(archive_path.read_bytes()).hexdigest() == report["archive_sha256"]
    with tarfile.open(archive_path, "r:gz") as archived:
        names = set(archived.getnames())
        assert names == {
            "BUNDLE_INDEX.json", "QUARANTINE_INTENT.json",
            "assets/safe.jsonl.gz", "manifests/safe.json",
        }
        index = json.load(archived.extractfile("BUNDLE_INDEX.json"))
        assert index["manifests"] == ["manifests/safe.json"]
        assert index["reject_count"] == 0
        intent = json.load(archived.extractfile("QUARANTINE_INTENT.json"))
        assert intent["status"] == "QUARANTINE_NOT_REPLAY_CERTIFIED"
    assert (root / "assets" / "bad.jsonl.gz").is_file()


def test_oversized_failed_market_bundle_preserves_bounded_subset_in_quarantine(tmp_path):
    root, result = make_bundle(tmp_path)
    first_manifest = root / "manifests" / "safe.json"
    second_manifest = root / "manifests" / "safe-second.json"
    other = json.loads(first_manifest.read_text(encoding="utf-8"))
    other["dataset_id"] = "pending-remote-2"
    other["release_asset"] = "safe-second.jsonl.gz"
    second_manifest.write_text(json.dumps(other), encoding="utf-8")
    (root / "assets" / "safe-second.jsonl.gz").write_bytes(
        (root / "assets" / "safe.jsonl.gz").read_bytes()
    )
    index_file = root / "BUNDLE_INDEX.json"
    index = json.loads(index_file.read_text(encoding="utf-8"))
    index["manifests"].append("manifests/safe-second.json")
    index["assets"].append("assets/safe-second.jsonl.gz")
    index_file.write_text(json.dumps(index), encoding="utf-8")
    first_bytes = first_manifest.stat().st_size + (root / "assets" / "safe.jsonl.gz").stat().st_size
    second_bytes = second_manifest.stat().st_size + (root / "assets" / "safe-second.jsonl.gz").stat().st_size

    archive = tmp_path / "partial-quarantine.tgz"
    report = module.preserve(result, archive, max_bytes=first_bytes + second_bytes // 2)
    assert report["status"] == "QUARANTINE_ARCHIVED"
    assert report["candidate_shards"] == 1
    assert report["omitted_due_budget"] == 1
    assert report["source_coverage_complete"] is False
    assert report["archive_bytes"] <= first_bytes + second_bytes // 2
    with tarfile.open(archive, "r:gz") as archived:
        names = set(archived.getnames())
        assert "assets/safe.jsonl.gz" in names
        assert "assets/safe-second.jsonl.gz" not in names
        intent = json.load(archived.extractfile("QUARANTINE_INTENT.json"))
        assert intent["source_coverage_complete"] is False
        assert intent["status"] == "QUARANTINE_NOT_REPLAY_CERTIFIED"


def test_failed_publish_fallback_refuses_partial_transfer_when_over_budget(tmp_path):
    _, result = make_bundle(tmp_path)
    archive = tmp_path / "too-small.tgz"
    report = module.preserve(result, archive, max_bytes=1)
    assert report["status"] == "QUARANTINE_SKIPPED_BUDGET"
    assert not archive.exists()


def test_failed_publish_fallback_rejects_corrupted_candidate_bytes(tmp_path):
    root, result = make_bundle(tmp_path)
    (root / "assets" / "safe.jsonl.gz").write_bytes(b"wrong")
    with pytest.raises(ValueError, match="QUARANTINE_ASSET_SHA_MISMATCH"):
        module.preserve(result, tmp_path / "invalid.tgz")
    assert not (tmp_path / "invalid.tgz").exists()
