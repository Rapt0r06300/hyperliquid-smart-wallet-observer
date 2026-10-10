"""Cloud CI regression for lossless, fail-closed catalogue partition planning."""
import json

import pytest

from tools.partitioned_data_index import load_partitioned_index, partition_index


def _index():
    return {
        "schema": "alina.data_index.v2",
        "release_repository_default": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "run_manifest_release_tags_by_release": {"part-1": "run-1"},
        "active_data_status": "SAFE",
        "shards": [
            {"dataset_id": f"data-{i:03d}", "quality_status": "SAFE",
             "release_tag": "part-1", "sha256": f"{i:064x}",
             "nested": {"replay_compatible": True, "economics": [i, 0]}}
            for i in range(9)
        ],
    }


def _stage(tmp_path, root, files):
    catalog = tmp_path / "catalog"
    catalog.mkdir(exist_ok=True)
    index_path = catalog / "DATA_INDEX.json"
    index_path.write_text(json.dumps(root), encoding="utf-8")
    for name, content in files.items():
        destination = catalog / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    return index_path


def test_partition_plan_exact_roundtrip_stable_and_no_live_mutation(tmp_path):
    original = _index()
    before = json.dumps(original, sort_keys=True)
    root, files = partition_index(original, max_partition_bytes=240)
    root_again, files_again = partition_index(original, max_partition_bytes=240)
    assert (root, files) == (root_again, files_again)
    assert len(files) > 1
    assert json.dumps(original, sort_keys=True) == before
    assert load_partitioned_index(_stage(tmp_path, root, files)) == original


def test_partition_refuses_tampered_evidence(tmp_path):
    root, files = partition_index(_index(), max_partition_bytes=240)
    path = _stage(tmp_path, root, files)
    first = next(iter(files))
    (path.parent / first).write_bytes(files[first] + b" ")
    with pytest.raises(ValueError, match="PARTITION_PARITY_DIGEST_MISMATCH"):
        load_partitioned_index(path)


def test_partition_refuses_missing_file(tmp_path):
    root, files = partition_index(_index(), max_partition_bytes=240)
    path = _stage(tmp_path, root, files)
    (path.parent / next(iter(files))).unlink()
    with pytest.raises(ValueError, match="PARTITION_PARITY_MISSING_FILE"):
        load_partitioned_index(path)


def test_partition_refuses_path_escape_and_missing_partition(tmp_path):
    root, files = partition_index(_index(), max_partition_bytes=240)
    root["partitions"][0]["path"] = "../outside.json"
    with pytest.raises(ValueError, match="PARTITION_PARITY_INVALID_PATH"):
        load_partitioned_index(_stage(tmp_path, root, files))


def test_partition_refuses_duplicate_dataset_id_and_oversize_row():
    original = _index()
    original["shards"][1]["dataset_id"] = original["shards"][0]["dataset_id"]
    with pytest.raises(ValueError, match="DUPLICATE_OR_MISSING_DATASET_ID"):
        partition_index(original)
    original = _index()
    original["shards"][0]["huge"] = "x" * 2000
    with pytest.raises(ValueError, match="SINGLE_ROW_OVERSIZE"):
        partition_index(original, max_partition_bytes=240)


def test_partition_refuses_global_count_mismatch(tmp_path):
    root, files = partition_index(_index(), max_partition_bytes=240)
    root["shard_count"] += 1
    with pytest.raises(ValueError, match="PARTITION_PARITY_GLOBAL_MISMATCH"):
        load_partitioned_index(_stage(tmp_path, root, files))
