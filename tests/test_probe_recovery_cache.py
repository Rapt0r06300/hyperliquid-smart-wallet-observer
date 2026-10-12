"""Synthetic byte proof against an offline Release cache; no reclassification."""
from __future__ import annotations

import hashlib
import io
import zipfile

from tools.probe_recovery_cache import probe_cache


def _row(sha, *, outer_digest, outer_size, **kw):
    row = {
        "dataset_id": "shard", "quality_status": "PARTIAL", "family": "trades",
        "replay_compatible": False, "release_tag": "tag",
        "release_asset": "shard.jsonl.gz", "release_container_asset": "bundle.zip",
        "release_remote_digest": "sha256:" + outer_digest,
        "release_remote_size": outer_size,
        "bytes": 15, "sha256": sha,
    }
    row.update(kw)
    return row


def _zip_fixture(tmp_path, inner):
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as zf:
        zf.writestr("shard.jsonl.gz", inner)
    blob = data.getvalue()
    root = tmp_path / "releases"
    (root / "tag").mkdir(parents=True)
    (root / "tag" / "bundle.zip").write_bytes(blob)
    return root, blob


def test_probe_verified_inner_bytes_still_never_promotes(tmp_path):
    inner = b"123456789012345"
    root, outer = _zip_fixture(tmp_path, inner)
    index = {"shards": [_row(hashlib.sha256(inner).hexdigest(),
                            outer_digest=hashlib.sha256(outer).hexdigest(),
                            outer_size=len(outer))]}
    report = probe_cache(index, root, max_candidates=1, max_verify_bytes=100000)
    assert report["cached_shards_byte_verified"] == 1
    assert report["source_check_counts"] == {
        "BYTE_VERIFIED_NON_SAFE_NOT_REPLAY_CERTIFIED": 1}
    assert report["verification_bytes_read"] == len(outer) + len(inner)
    assert report["repair_succeeded"] is False
    assert report["replay_certified"] is False
    assert (root / "tag" / "bundle.zip").read_bytes() == outer


def test_probe_refuses_corruption_and_missing_inner_identity(tmp_path):
    inner = b"123456789012345"
    root, outer = _zip_fixture(tmp_path, inner)
    digest = hashlib.sha256(outer).hexdigest()
    scenarios = [
        (_row("b"*64, outer_digest=digest, outer_size=len(outer)), "SHARD_BYTES_MISMATCH"),
        (_row(hashlib.sha256(inner).hexdigest(), outer_digest="a"*64,
              outer_size=len(outer)), "SOURCE_OUTER_SHA_MISMATCH"),
        (_row("", outer_digest=digest, outer_size=len(outer)), "INDEX_IDENTITY_INCOMPLETE"),
    ]
    for row, expected in scenarios:
        report = probe_cache({"shards": [row]}, root, max_verify_bytes=100000)
        assert report["results"][0]["source_check"] == expected
        assert report["cached_shards_byte_verified"] == 0
    assert (root / "tag" / "bundle.zip").read_bytes() == outer


def test_probe_budget_and_absence_never_imply_irrecoverable(tmp_path):
    inner = b"123456789012345"
    root, outer = _zip_fixture(tmp_path, inner)
    row = _row(hashlib.sha256(inner).hexdigest(),
               outer_digest=hashlib.sha256(outer).hexdigest(), outer_size=len(outer))
    report = probe_cache({"shards": [row]}, root, max_verify_bytes=len(outer)-1)
    assert report["results"][0]["source_check"] == "VERIFY_BYTE_BUDGET_EXCEEDED"
    (root / "tag" / "bundle.zip").unlink()
    report = probe_cache({"shards": [row]}, root, max_verify_bytes=100000)
    assert report["results"][0]["source_check"] == "SOURCE_NOT_CACHED"
    assert report["all_exploitable_data_restored"] is False


def test_probe_candidate_offset_processes_next_batch_without_promoting(tmp_path):
    inner = b"123456789012345"
    root, blob = _zip_fixture(tmp_path, inner)
    row = _row(hashlib.sha256(inner).hexdigest(),
               outer_digest=hashlib.sha256(blob).hexdigest(),
               outer_size=len(blob))
    first = dict(row, dataset_id="one")
    second = dict(row, dataset_id="two")
    result = probe_cache({"shards": [first, second]}, root,
                         max_candidates=1, candidate_offset=1, max_verify_bytes=100000)
    assert result["candidate_offset"] == 1
    assert result["candidates_total"] == 2
    assert result["candidates_checked"] == 1
    assert result["results"][0]["dataset_id"] == "two"
    assert result["cached_shards_byte_verified"] == 1
