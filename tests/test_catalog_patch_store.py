from __future__ import annotations

import json

import pytest

from tools import catalog_patch_store as store


def test_legacy_inline_patch_remains_readable(tmp_path):
    path = tmp_path / "RECORD_COUNT_PATCH.json"
    expected = {"schema": "legacy", "records": {"a": {"record_count": 2}}}
    path.write_text(json.dumps(expected), encoding="utf-8")
    assert store.read_catalog_patch(path, expected_table="records") == expected


def test_partitioned_patch_round_trips_without_losing_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MAX_PARTITION_BYTES", 512)
    path = tmp_path / "RECORD_COUNT_PATCH.json"
    expected = {
        "schema": "alina.record_count_patch.v1",
        "coverage_complete": True,
        "records": {
            f"asset-{number:03d}": {"record_count": number, "label": "x" * 45} for number in range(30)
        },
    }
    store.write_catalog_patch(path, expected, table="records", inline_limit_bytes=64)
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert "records" not in manifest
    assert manifest["storage"]["entry_count"] == 30
    assert len(manifest["storage"]["partitions"]) > 1
    assert all(part["size_bytes"] <= 512 for part in manifest["storage"]["partitions"])
    assert store.read_catalog_patch(path, expected_table="records") == expected


def test_partition_reader_rejects_corrupt_part(tmp_path):
    path = tmp_path / "RECORD_COUNT_PATCH.json"
    store.write_catalog_patch(
        path, {"records": {"a": {"exact": True}}}, table="records", inline_limit_bytes=1
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    part = path.parent / manifest["storage"]["directory"] / manifest["storage"]["partitions"][0]["name"]
    part.write_bytes(part.read_bytes() + b" ")
    with pytest.raises(ValueError, match="INTEGRITY_FAILURE"):
        store.read_catalog_patch(path, expected_table="records")


def test_partition_reader_rejects_missing_part(tmp_path):
    path = tmp_path / "RECORD_COUNT_PATCH.json"
    store.write_catalog_patch(
        path, {"records": {"a": {"exact": True}}}, table="records", inline_limit_bytes=1
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    part = path.parent / manifest["storage"]["directory"] / manifest["storage"]["partitions"][0]["name"]
    part.unlink()
    with pytest.raises(ValueError, match="PART_MISSING_OR_UNSAFE"):
        store.read_catalog_patch(path, expected_table="records")


def test_writer_keeps_unmanaged_neighbor_files_and_removes_only_old_parts(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MAX_PARTITION_BYTES", 512)
    path = tmp_path / "RECORD_COUNT_PATCH.json"
    rows = {f"id-{number:03d}": {"v": "a" * 40} for number in range(20)}
    store.write_catalog_patch(path, {"records": rows}, table="records", inline_limit_bytes=1)
    directory = tmp_path / "record-count-patch-parts"
    (directory / "notes.txt").write_text("keep", encoding="utf-8")
    store.write_catalog_patch(path, {"records": {"new": {"v": 1}}}, table="records", inline_limit_bytes=1)
    assert (directory / "notes.txt").read_text(encoding="utf-8") == "keep"
    assert store.read_catalog_patch(path, expected_table="records")["records"] == {"new": {"v": 1}}


def test_partition_table_mismatch_fails_closed(tmp_path):
    path = tmp_path / "RECORD_COUNT_PATCH.json"
    store.write_catalog_patch(
        path, {"records": {"a": {"exact": True}}}, table="records", inline_limit_bytes=1
    )
    with pytest.raises(ValueError, match="TABLE_MISMATCH"):
        store.read_catalog_patch(path, expected_table="sizes")
