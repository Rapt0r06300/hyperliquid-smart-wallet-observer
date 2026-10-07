from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "verify_fresh_clone_lfs_streaming_test",
        ROOT / "tools" / "verify_fresh_clone_lfs_streaming.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _row(asset_id: int, path: str, size: int = 10) -> dict:
    return {
        "asset_id": asset_id,
        "clone_path": path,
        "bytes": size,
        "sha256": hashlib.sha256(path.encode("utf-8")).hexdigest(),
    }


def test_parse_pointer_accepts_exact_lfs_identity():
    module = _module()
    oid = "a" * 64
    raw = (
        "version https://git-lfs.github.com/spec/v1\n"
        f"oid sha256:{oid}\n"
        "size 123\n"
    )

    assert module.parse_pointer(raw) == (oid, 123)


def test_parse_pointer_rejects_non_lfs_content():
    module = _module()
    try:
        module.parse_pointer("real payload bytes\n")
    except module.StreamingCloneError as exc:
        assert "not a Git LFS pointer" in str(exc)
    else:
        raise AssertionError("non-LFS content must fail closed")


def test_shard_rows_partitions_manifest_without_overlap(tmp_path):
    module = _module()
    rows = [_row(i + 1, f"clone_payload/releases/t{i}.bin") for i in range(12)]

    shards = [
        module.shard_rows(rows, root=tmp_path, shard_count=4, shard_index=i)
        for i in range(4)
    ]

    ids = [{row["asset_id"] for row in shard} for shard in shards]
    assert set.union(*ids) == set(range(1, 13))
    assert sum(len(shard) for shard in shards) == 12
    for i in range(4):
        for j in range(i + 1, 4):
            assert ids[i].isdisjoint(ids[j])


def test_plan_batches_respects_asset_and_byte_bounds():
    module = _module()
    rows = [
        _row(1, "clone_payload/releases/a.bin", 40),
        _row(2, "clone_payload/releases/b.bin", 40),
        _row(3, "clone_payload/releases/c.bin", 40),
        _row(4, "clone_payload/releases/d.bin", 5),
    ]

    batches = module.plan_batches(rows, max_assets=2, max_bytes=70)

    assert [[row["asset_id"] for row in batch] for batch in batches] == [
        [1],
        [2],
        [3, 4],
    ]


def test_plan_batches_allows_single_object_larger_than_soft_byte_bound():
    module = _module()
    rows = [_row(1, "clone_payload/releases/large.bin", 200)]

    batches = module.plan_batches(rows, max_assets=10, max_bytes=100)

    assert len(batches) == 1
    assert batches[0][0]["bytes"] == 200


def test_safe_row_rejects_path_escape_and_commas(tmp_path):
    module = _module()
    base = _row(1, "../escape.bin")
    try:
        module.safe_row(base, root=tmp_path)
    except module.StreamingCloneError:
        pass
    else:
        raise AssertionError("path escape must fail")

    comma = _row(2, "clone_payload/releases/a,b.bin")
    try:
        module.safe_row(comma, root=tmp_path)
    except module.StreamingCloneError:
        pass
    else:
        raise AssertionError("comma path must fail because LFS include list is comma-delimited")


def test_load_manifest_requires_expected_schema(tmp_path):
    module = _module()
    manifest = tmp_path / "clone_payload" / "MANIFEST.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"schema": "wrong", "entries": []}), encoding="utf-8")

    try:
        module.load_manifest(tmp_path)
    except module.StreamingCloneError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("wrong manifest schema must fail")
