"""Measurement must never silently ignore data in a partitioned Dataset index."""
import json
import sys

from tools.partitioned_data_index import partition_index
from tools import measure_uncompressed_sizes as measurement


def test_measure_sizes_from_verified_partitioned_index(tmp_path, monkeypatch):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    source = {
        "schema": "alina.data_index.v2",
        "release_repository_default": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "shards": [{
            "dataset_id": "one-asset",
            "release_tag": "data-v2-test",
            "release_asset": "data.jsonl.gz",
            "sha256": "a" * 64,
            "bytes": 10,
        }],
    }
    root, parts = partition_index(source)
    index = catalog / "DATA_INDEX.json"
    index.write_text(json.dumps(root), encoding="utf-8")
    for rel, content in parts.items():
        dest = catalog / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    before = index.read_bytes()
    size_patch, records_patch = catalog / "sizes.json", catalog / "records.json"
    monkeypatch.setattr(measurement, "INDEX", index)
    monkeypatch.setattr(measurement, "SIZE_PATCH", size_patch)
    monkeypatch.setattr(measurement, "RECORD_PATCH", records_patch)
    observed = []
    def measure(row, _temporary_root):
        observed.append(row["dataset_id"])
        return row["dataset_id"], {
            "uncompressed_bytes": 100, "asset_sha256": row["sha256"],
        }, {
            "record_count": 2, "valid_record_count": 2,
            "unique_record_count": 2, "exact": True,
            "asset_sha256": row["sha256"],
        }
    monkeypatch.setattr(measurement, "_measure_candidate", measure)
    monkeypatch.setattr(sys, "argv", ["measure_uncompressed_sizes.py", "--limit", "1", "--workers", "1"])
    measurement.main()
    assert observed == ["one-asset"]
    assert json.loads(size_patch.read_text())["sizes"]["one-asset"]["uncompressed_bytes"] == 100
    assert json.loads(records_patch.read_text())["records"]["one-asset"]["record_count"] == 2
    assert index.read_bytes() == before
