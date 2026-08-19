from __future__ import annotations

import gzip
import hashlib
import json
import zipfile

import pytest

import hl_observer.datasets.github_release_bridge as bridge


def _asset(name="asset.bin", data=b"abc", *, asset_id=1) -> bridge.ReleaseAsset:
    return bridge.ReleaseAsset(
        asset_id=asset_id,
        name=name,
        size=len(data),
        digest="sha256:" + hashlib.sha256(data).hexdigest(),
    )


def test_release_asset_record_manifest_and_selection(tmp_path) -> None:
    asset = bridge.ReleaseAsset(1, "x", 3, "sha256:abc")
    assert asset.sha256 == "abc"
    assert bridge.ReleaseAsset(1, "x", 3, "md5:abc").sha256 == ""
    record = bridge.DatasetRecord.from_mapping({
        "relative_path": "a/b.json",
        "size": "3",
        "sha256": "ff",
        "storage": "raw_chunks",
        "chunks": [{"asset": "p2", "part": 2}, "bad", {"asset": "p1", "part": 1}],
    })
    assert record.needed_assets() == ("p2", "p1")

    manifest = tmp_path / "m.jsonl.gz"
    lines = [
        "",
        json.dumps([1, 2]),
        json.dumps({"relative_path": "a.json", "size": 1, "storage": "zip_entry", "asset": "z.zip"}),
        json.dumps({"relative_path": "b.csv", "size": 2, "storage": "raw_chunks", "chunks": [{"asset": "p1"}]}),
    ]
    with gzip.open(manifest, "wt", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    records = list(bridge.iter_manifest_records(manifest))
    assert [item.relative_path for item in records] == ["a.json", "b.csv"]
    assert [item.relative_path for item in bridge.select_records(records, contains=["a."], suffixes=["json"])] == ["a.json"]
    assert bridge.assets_for_records(records) == ("p1", "z.zip")


def test_verify_asset_safe_destination_and_materialization(tmp_path) -> None:
    data = b"abc"
    asset = _asset(data=data)
    path = tmp_path / asset.name
    path.write_bytes(data)
    bridge.verify_asset(path, asset)
    with pytest.raises(bridge.DatasetBridgeError, match="Chemin dangereux"):
        bridge._safe_destination(tmp_path, "../escape")

    out = tmp_path / "out"
    archive = tmp_path / "z.zip"
    zip_data = b"hello"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("nested/a.txt", zip_data)
    zipped = bridge.DatasetRecord(
        "nested/a.txt",
        len(zip_data),
        hashlib.sha256(zip_data).hexdigest(),
        "zip_entry",
        "z.zip",
    )
    created = bridge.materialize_records([zipped], {"z.zip": archive}, out)
    assert created[0].read_bytes() == zip_data

    p1 = tmp_path / "p1"
    p2 = tmp_path / "p2"
    p1.write_bytes(b"ab")
    p2.write_bytes(b"cd")
    raw = bridge.DatasetRecord(
        "raw.bin",
        4,
        hashlib.sha256(b"abcd").hexdigest(),
        "raw_chunks",
        chunks=({"asset": "p2", "part": 2}, {"asset": "p1", "part": 1}),
    )
    assert bridge.materialize_records([raw], {"p1": p1, "p2": p2}, out)[0].read_bytes() == b"abcd"


def test_materialization_fail_closed(tmp_path) -> None:
    out = tmp_path / "out"
    with pytest.raises(bridge.DatasetBridgeError, match="Stockage inconnu"):
        bridge.materialize_records([bridge.DatasetRecord("x", 0, "", "bad")], {}, out)
    with pytest.raises(bridge.DatasetBridgeError, match="Aucun morceau"):
        bridge.materialize_records([
            bridge.DatasetRecord("x", 0, "", "raw_chunks", chunks=())
        ], {}, out)
    with pytest.raises(bridge.DatasetBridgeError, match="Morceau non téléchargé"):
        bridge.materialize_records([
            bridge.DatasetRecord("x", 1, "", "raw_chunks", chunks=({"asset": "m", "part": 1},))
        ], {}, out)
