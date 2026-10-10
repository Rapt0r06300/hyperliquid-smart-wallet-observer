"""Regression: historical SAFE repair must understand verified partitioned catalogs."""
import json

import pytest

from tools.partitioned_data_index import partition_index
from tools.repair_stale_safe_classifications import repair


def _partitioned_catalog(tmp_path):
    catalog = tmp_path / "catalog"
    catalog.mkdir()
    original = {
        "schema": "alina.data_index.v2",
        "active_data_status": "PARTIAL",
        "release_repository_default": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "shards": [{
            "dataset_id": "missing-proof",
            "quality_status": "PARTIAL",
            "manifest_path": "datasets/quarantine/missing-proof.manifest.json",
            "sha256": "a" * 64,
            "event_count": 1,
        }],
    }
    root, parts = partition_index(original)
    index = catalog / "DATA_INDEX.json"
    index.write_text(json.dumps(root), encoding="utf-8")
    for rel, content in parts.items():
        dest = catalog / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
    (catalog / "DATA_QUALITY_REGISTRY.json").write_text("{}", encoding="utf-8")
    (catalog / "DATA_CATALOG.json").write_text("{}", encoding="utf-8")
    return index, parts


def test_repair_unproven_partitioned_shard_stays_quarantined(tmp_path):
    index, parts = _partitioned_catalog(tmp_path)
    before = index.read_bytes()
    result = repair(tmp_path)
    assert result["repaired_count"] == 0
    assert result["safe_count"] == 0
    assert result["partial_count"] == 1
    assert index.read_bytes() == before
    for rel, expected in parts.items():
        assert (index.parent / rel).read_bytes() == expected


def test_repair_refuses_tampered_partition_before_classification(tmp_path):
    index, parts = _partitioned_catalog(tmp_path)
    part = index.parent / next(iter(parts))
    part.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="PARTITION_PARITY_(SIZE|DIGEST)_MISMATCH"):
        repair(tmp_path)
