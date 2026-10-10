"""Exact trade-count backfills refuse missing/tampered partition evidence."""
import json
import sys

import pytest

from tools.partitioned_data_index import partition_index
from tools import backfill_exact_trade_counts as exact
from tools import backfill_global_unique_trade_counts as global_unique


def _corrupt_partition(tmp_path):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    logical = {
        "schema": "alina.data_index.v2",
        "shards": [{
            "dataset_id": "trades-shard",
            "quality_status": "SAFE",
            "family": "trades",
            "sha256": "a" * 64,
            "trade_count_exact": True,
            "trade_count": 2,
        }],
    }
    root, parts = partition_index(logical)
    index = catalog / "DATA_INDEX.json"
    index.write_text(json.dumps(root), encoding="utf-8")
    part = catalog / next(iter(parts))
    part.parent.mkdir(parents=True, exist_ok=True)
    part.write_bytes(b"corrupted bytes")
    return index


def test_exact_trade_backfill_fails_before_asset_scan_on_corrupt_partition(tmp_path, monkeypatch):
    index = _corrupt_partition(tmp_path)
    monkeypatch.setattr(exact, "INDEX_PATH", index)
    monkeypatch.setattr(exact, "_download", lambda *_a, **_k: (
        _ for _ in ()).throw(AssertionError("no downloads on bad index")))
    with pytest.raises(ValueError, match="PARTITION_PARITY_(SIZE|DIGEST)_MISMATCH"):
        exact.backfill(1)


def test_global_unique_count_fails_before_asset_scan_on_corrupt_partition(tmp_path, monkeypatch):
    index = _corrupt_partition(tmp_path)
    monkeypatch.setattr(global_unique, "INDEX_PATH", index)
    monkeypatch.setattr(sys, "argv", ["backfill_global_unique_trade_counts.py", "--limit", "1"])
    monkeypatch.setattr(global_unique, "_scan_candidate", lambda *_a, **_k: (
        _ for _ in ()).throw(AssertionError("no scans on bad index")))
    with pytest.raises(ValueError, match="PARTITION_PARITY_(SIZE|DIGEST)_MISMATCH"):
        global_unique.main()
