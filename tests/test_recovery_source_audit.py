"""Deterministic SHA-bound source audit: inventory presence is not recovery."""
from __future__ import annotations

import gzip
import hashlib
import json

import pytest

from tools.audit_recovery_sources import (
    assess_sources, read_source_inventory,
)
from tools.preservation_inventory import InventoryError, summarize, write_recovery_triage, verify_recovery_triage

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def _row(ident, status, **kw):
    row = {
        "dataset_id": ident, "family": "l2book", "quality_status": status,
        "sha256": SHA_A, "bytes": 100, "release_tag": "r1",
        "release_asset": ident + ".gz", "release_container_asset": "bundle.zip",
        "release_remote_size": 400, "release_remote_digest": "sha256:" + SHA_B,
        "replay_compatible": False,
    }
    row.update(kw)
    return row


def _inventory():
    return {
        "schema": "alina.restore_inventory.v1",
        "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "generated_at_utc": "2026-10-12T00:00:00Z",
        "release_count": 1, "asset_count": 2, "source_asset_bytes": 550,
        "releases": [{
            "id": 12, "tag_name": "r1", "assets": [
                {"id": 3, "name": "bundle.zip", "size": 400,
                 "digest": "sha256:" + SHA_B, "state": "uploaded"},
                {"id": 4, "name": "conflict.zip", "size": 150,
                 "digest": "sha256:" + SHA_C, "state": "uploaded"},
            ],
        }],
    }


def _fixture(tmp_path, index):
    rows = index["shards"]
    metrics = {
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": SHA_A,
        "totals": {"TOTAL_SHARDS": len(rows), "GLOBAL_UNIQUE_TRADES_COVERAGE_COMPLETE": False},
    }
    report = summarize(index, metrics, SHA_A)
    triage = tmp_path / "candidates.jsonl"
    write_recovery_triage(index, report, triage)
    assert verify_recovery_triage(index, report, triage)["candidate_count"] == len(rows)
    return report


def test_audit_matches_outer_assets_without_promoting_any_shard(tmp_path):
    index = {"shards": [
        _row("a", "PARTIAL"),
        _row("b", "REJECT", release_container_asset="absent.zip"),
        _row("c", "STALE", release_container_asset="conflict.zip"),
        _row("d", "PARTIAL", release_remote_digest=""),
    ]}
    report = _fixture(tmp_path, index)
    path = tmp_path / "RESTORE_INVENTORY.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as stream:
        json.dump(_inventory(), stream)
    assets, meta = read_source_inventory(path)
    outcome, detail = assess_sources(index, report, assets, meta)
    assert outcome["candidate_count"] == 4
    assert [x["source_comparison"] for x in detail] == [
        "SNAPSHOT_ASSET_IDENTITY_MATCHED_NOT_DOWNLOADED",
        "NOT_LISTED_IN_SNAPSHOT",
        "SNAPSHOT_METADATA_CONFLICT",
        "SNAPSHOT_LISTED_IDENTITY_UNBOUND",
    ]
    assert outcome["unique_matched_outer_assets"] == 1
    assert outcome["unique_matched_outer_asset_bytes"] == 400
    assert outcome["recovered_shards"] is None
    assert outcome["all_exploitable_data_restored"] is False
    assert all(x["validation_allowed"] is False for x in detail)


def test_source_inventory_refuses_forged_count_duplicate_id_and_wrong_repository(tmp_path):
    path = tmp_path / "RESTORE_INVENTORY.json"
    data = _inventory()
    path.write_text(json.dumps(data), encoding="utf-8")
    assert read_source_inventory(path)[1]["source_snapshot_assets"] == 2
    data["asset_count"] = 1
    path.write_text(json.dumps(data))
    with pytest.raises(InventoryError, match="TOTALS_MISMATCH"):
        read_source_inventory(path)
    data = _inventory()
    data["releases"][0]["assets"][1]["id"] = 3
    path.write_text(json.dumps(data))
    with pytest.raises(InventoryError, match="DUPLICATE_ASSET"):
        read_source_inventory(path)
    data = _inventory()
    data["repository"] = "another/repo"
    path.write_text(json.dumps(data))
    with pytest.raises(InventoryError, match="INVALID_HEADER"):
        read_source_inventory(path)


def test_source_audit_rejects_duplicate_catalog_id():
    rows = [_row("same", "PARTIAL"), _row("same", "REJECT")]
    with pytest.raises(InventoryError, match="DUPLICATE_CATALOG_ID"):
        assess_sources({"shards": rows},
                       {"unresolved_unsafe_shards": 2, "safe_non_replayable_shards": 0},
                       {}, {})


def test_matched_zip_cannot_certify_missing_inner_shard_identity(tmp_path):
    index = {"shards": [
        _row("unbound", "PARTIAL", sha256="", release_asset=""),
    ]}
    report = _fixture(tmp_path, index)
    assets = {("r1", "bundle.zip"): (400, SHA_B)}
    summary, detail = assess_sources(index, report, assets, {})
    assert detail[0]["source_comparison"] == "SNAPSHOT_LISTED_IDENTITY_UNBOUND"
    assert summary["unique_matched_outer_assets"] == 0
