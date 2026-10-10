"""Lossless snapshot checks, including tamper and duplicate fail-closed behavior."""
import hashlib
import json

import pytest

from tools.catalog_index_partitions import PartitionError, build_snapshot, load_snapshot


def _source(tmp_path, rows):
    index = tmp_path / "DATA_INDEX.json"
    data = {"active_data_status": "PARTIAL", "shards": rows}
    index.write_text(json.dumps(data), encoding="utf-8")
    return index


def test_partition_snapshot_roundtrip_is_idempotent_and_source_immutable(tmp_path):
    rows = [
        {"dataset_id": f"asset-{i}", "quality_status": "SAFE" if i % 2 else "REJECT",
         "sha256": hashlib.sha256(str(i).encode()).hexdigest(), "event_count": i + 1}
        for i in range(400)
    ]
    index = _source(tmp_path, rows)
    before = index.read_bytes()
    out = tmp_path / "parts"
    first = build_snapshot(index, out)
    assert first["status"] == "VERIFIED_NEW"
    assert index.read_bytes() == before
    recovered = load_snapshot(out / ("index-" + first["source_index_sha256"]) / "MANIFEST.json")
    assert sorted(recovered["shards"], key=lambda row: row["dataset_id"]) == sorted(
        rows, key=lambda row: row["dataset_id"])
    assert recovered["source_metadata"]["active_data_status"] == "PARTIAL"
    assert build_snapshot(index, out)["status"] == "VERIFIED_EXISTING"


def test_snapshot_rejects_duplicate_id_before_writing(tmp_path):
    index = _source(tmp_path, [{"dataset_id": "x"}, {"dataset_id": "x"}])
    with pytest.raises(PartitionError, match="duplicate"):
        build_snapshot(index, tmp_path / "output")
    assert not (tmp_path / "output").exists()


def test_snapshot_fails_closed_on_tampered_partition(tmp_path):
    index = _source(tmp_path, [{"dataset_id": "evidence"}])
    result = build_snapshot(index, tmp_path / "parts")
    folder = tmp_path / "parts" / ("index-" + result["source_index_sha256"])
    inventory = json.loads((folder / "MANIFEST.json").read_text())
    partition = folder / inventory["partitions"][0]["name"]
    partition.write_bytes(b'{"shards":[]}')
    with pytest.raises(PartitionError, match="SHA/size mismatch"):
        load_snapshot(folder / "MANIFEST.json")


def test_snapshot_refuses_bad_partition_size_and_identity(tmp_path):
    index = _source(tmp_path, [{"dataset_id": "x"}])
    with pytest.raises(PartitionError, match="too small"):
        build_snapshot(index, tmp_path / "output", max_partition_bytes=2)
