from __future__ import annotations

import gzip
import hashlib

from hl_observer.backtesting.copy_vault_local_lab import hash_cache_invalidation_receipt
from hl_observer.datasets.dataset_untrusted_guard import untrusted_provenance_receipt
from hl_observer.datasets.github_release_bridge import DatasetRecord, ReleaseAsset, release_publication_receipt
from hl_observer.datasets.progress_downloader import resume_transfer_receipt
from hl_observer.datasets.release_gateway import release_asset_verification_receipt
from hl_observer.datasets.replay_coverage import safe_coverage_receipt
from hl_observer.datasets.replay_workspace import deduplicate_release_sessions
from hl_observer.datasets.streaming_materializer import materialization_safety_receipt
from hl_observer.datasets.v2_pipeline import partial_recovery_receipt
from hl_observer.datasets.v2_reader import recount_shard_lines_receipt


def test_131_untrusted_workspace_is_scanned_fail_closed(tmp_path) -> None:
    result = untrusted_provenance_receipt(tmp_path)
    assert result["status"] == "PROVEN"
    assert result["scripts_or_executables_allowed"] is False


def test_132_partial_download_is_resumable_without_mutation(tmp_path) -> None:
    asset = ReleaseAsset(asset_id=1, name="sample.bin", size=10, digest="sha256:" + "0" * 64)
    partial = tmp_path / "data" / "hypersmart_datasets" / "assets" / "sample.bin.part"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"1234")
    result = resume_transfer_receipt(tmp_path, {asset.name: asset}, [asset.name])
    assert result["status"] == "PROVEN"
    assert result["partial_names"] == [asset.name]
    assert result["non_destructive"] is True


def test_133_release_asset_requires_matching_hash(tmp_path) -> None:
    payload = b"release-safe"
    path = tmp_path / "asset.bin"
    path.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    asset = ReleaseAsset(asset_id=1, name=path.name, size=len(payload), digest="sha256:" + digest)
    result = release_asset_verification_receipt(path, asset, repository="repo", release_tag="data-v2-run-1")
    assert result["status"] == "PROVEN"
    assert result["sha256"] == digest


def test_134_release_publication_rejects_missing_digest() -> None:
    result = release_publication_receipt({"tag_name": "data-v2-run-1", "draft": False, "assets": [{"id": 1, "name": "a", "size": 1, "digest": "sha256:" + "0" * 64}]}, ["a"])
    assert result["status"] == "PROVEN"


def test_135_materialization_rejects_path_traversal() -> None:
    rows = [DatasetRecord(relative_path="../escape", size=1, sha256="", storage="raw_chunks", chunks=({"asset": "a", "part": 1},))]
    result = materialization_safety_receipt(__import__("pathlib").Path("."), rows)
    assert result["status"] == "REJECTED"


def test_136_recount_after_reindex_is_exact(tmp_path) -> None:
    path = tmp_path / "shard.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write('{"event":1}\n\n{"event":2}\n')
    result = recount_shard_lines_receipt(path, expected_event_count=2)
    assert result["status"] == "PROVEN"
    assert result["exact"] is True


def test_137_safe_coverage_requires_full_requested_window() -> None:
    manifests = [{"quality_status": "SAFE", "validation_allowed": True, "asset_verified": True, "venue": "x", "family": "copy_vault_fills", "symbol": "BTC", "start_ts_ms": 100, "end_ts_ms": 300, "event_count": 2, "bytes": 10, "dataset_id": "d1"}]
    result = safe_coverage_receipt(manifests, required_start_ts_ms=150, required_end_ts_ms=250)
    assert result["status"] == "PROVEN"
    assert result["covering_partitions"] == 1


def test_138_release_sessions_are_deduplicated() -> None:
    result = deduplicate_release_sessions([{"release_id": "1", "tag_name": "data-v2-run-1"}, {"release_id": "1", "tag_name": "data-v2-run-1"}])
    assert result["status"] == "PROVEN"
    assert result["unique_count"] == 1


def test_139_only_non_integrity_partial_is_recoverable() -> None:
    result = partial_recovery_receipt({"quality_status": "PARTIAL", "quality_reasons": ["REMOTE_ASSET_NOT_VERIFIED"]})
    assert result["status"] == "PROVEN"
    rejected = partial_recovery_receipt({"quality_status": "PARTIAL", "quality_reasons": ["SEQUENCE_OR_QUEUE_GAP"]})
    assert rejected["status"] == "REJECTED"


def test_140_changed_asset_invalidates_cache() -> None:
    result = hash_cache_invalidation_receipt(previous_asset_sha256="a" * 64, current_asset_sha256="b" * 64, cached_asset_sha256="a" * 64)
    assert result["status"] == "PROVEN"
    assert result["cache_invalidated"] is True
