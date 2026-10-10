from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from index_run_manifest import index_run_manifests  # noqa: E402


def _bootstrap_root(tmp_path: Path) -> Path:
    root = tmp_path / "dataset"
    for path in (
        "catalog",
        "datasets/incoming",
        "datasets/quarantine",
        "datasets/rejected",
        "datasets/safe",
    ):
        (root / path).mkdir(parents=True, exist_ok=True)
    (root / "catalog/DATA_INDEX.json").write_text(
        json.dumps(
            {
                "schema": "alina.data_index.v2",
                "generation": "V2_FRESH",
                "active_data_status": "NO_DATA",
                "shards": [],
            }
        ),
        encoding="utf-8",
    )
    (root / "catalog/DATA_CATALOG.json").write_text(
        json.dumps(
            {
                "schema": "alina.data_catalog.v2",
                "active_data_status": "NO_DATA",
            }
        ),
        encoding="utf-8",
    )
    (root / "catalog/DATA_QUALITY_REGISTRY.json").write_text(
        json.dumps(
            {
                "active_dataset": {
                    "status": "NO_DATA",
                    "validation_allowed": False,
                    "proof_of_pnl_allowed": False,
                }
            }
        ),
        encoding="utf-8",
    )
    return root


def _manifest(*, family: str, reconciliation: str, dataset_id: str) -> dict:
    return {
        "dataset_id": dataset_id,
        "family": family,
        "venue": "bybit",
        "symbol": "BTCUSDT",
        "start_ts_ms": 1000,
        "end_ts_ms": 2000,
        "sha256": "a" * 64,
        "bytes": 321,
        "event_count": 10,
        "trade_count": 10,
        "trade_count_exact": True,
        "unique_trade_count": 10,
        "unique_trade_count_exact": True,
        "collector_version": "b" * 40,
        "source": "bybit_public_ws",
        "quality_status": "SAFE",
        "asset_verified": True,
        "replay_compatible": True,
        "replay_schema_version": "alina.replay.v1",
        "replay_reason": "SMOKE_OK",
        "provenance": {
            "public_data_only": True,
            "authenticated": False,
            "real_execution": False,
            "transports": ["websocket"],
        },
        "integrity": {
            "gap_count": 0,
            "duplicate_count": 0,
            "regression_count": 0,
            "missing_timestamp_count": 0,
            "missing_monotonic_count": 0,
            "desync_count": 0,
            "duplicates_deduped": True,
        },
        "reconciliation": {"status": reconciliation},
        "required_channels": [],
        "observed_channels": [family],
        "cost_model": {"applicable": False, "ready": False},
        "release": {
            "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "tag": "data-v2-run-1-1-native",
            "release_id": 1,
            "asset_id": 2,
            "asset_name": dataset_id + ".jsonl.gz",
            "remote_size": 321,
            "remote_digest": "sha256:" + "a" * 64,
        },
    }


def _write_run(path: Path, manifests: list[dict]) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "alina.dataset_run_manifest.v2",
                "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
                "release_id": 1,
                "release_tag": "data-v2-run-1-1-native",
                "collector_version": "b" * 40,
                "shard_count": len(manifests),
                "manifests": manifests,
            }
        ),
        encoding="utf-8",
    )


def test_index_run_manifest_writes_complete_safe_row(tmp_path) -> None:
    root = _bootstrap_root(tmp_path)
    run = tmp_path / "RUN_MANIFEST.json"
    _write_run(
        run,
        [
            _manifest(
                family="l2Book",
                reconciliation="SOURCE_CONTINUITY_VERIFIED",
                dataset_id="l2-safe",
            )
        ],
    )

    result = index_run_manifests([run], root=root)
    assert result["active_data_status"] == "SAFE"

    index = json.loads((root / "catalog/DATA_INDEX.json").read_text())
    [row] = index["shards"]
    assert row["quality_status"] == "SAFE"
    assert row["bytes"] == 321
    assert index["release_repository_default"] == "Rapt0r06300/hyperliquid-smart-wallet-observer"
    assert "release_repository" not in row
    assert row["release_tag"] == "data-v2-run-1-1-native"
    assert row["release_asset"] == "l2-safe.jsonl.gz"
    assert (root / row["manifest_path"]).is_file()
    manifest = json.loads((root / row["manifest_path"]).read_text())
    assert manifest["validation_allowed"] is True
    assert manifest["proof_of_pnl_allowed"] is False
    catalog = json.loads((root / "catalog/DATA_CATALOG.json").read_text())
    assert catalog["active_data_status"] == "SAFE"
    assert catalog["indexed_shard_count"] == 1
    assert catalog["safe_shard_count"] == 1


def test_clean_live_trade_continuity_is_indexed_safe(tmp_path) -> None:
    root = _bootstrap_root(tmp_path)
    run = tmp_path / "RUN_MANIFEST.json"
    _write_run(
        run,
        [
            _manifest(
                family="trades",
                reconciliation="SOURCE_CONTINUITY_VERIFIED",
                dataset_id="trade-partial",
            )
        ],
    )

    result = index_run_manifests([run], root=root)
    assert result["active_data_status"] == "SAFE"

    index = json.loads((root / "catalog/DATA_INDEX.json").read_text())
    [row] = index["shards"]
    assert row["quality_status"] == "SAFE"
    manifest = json.loads((root / row["manifest_path"]).read_text())
    assert "RECONCILIATION_MATCH_REQUIRED" not in manifest["quality_reasons"]
    assert manifest["validation_allowed"] is True


def test_reindex_keeps_clean_continuity_trade_safe_when_reference_later_matches(tmp_path) -> None:
    root = _bootstrap_root(tmp_path)
    run = tmp_path / "RUN_MANIFEST.json"
    manifest = _manifest(
        family="trades",
        reconciliation="SOURCE_CONTINUITY_VERIFIED",
        dataset_id="trade-upgrade",
    )
    _write_run(run, [manifest])
    index_run_manifests([run], root=root)
    assert (root / "datasets/safe/trade-upgrade.manifest.json").is_file()

    manifest["reconciliation"] = {"status": "MATCHED"}
    _write_run(run, [manifest])
    index_run_manifests([run], root=root)
    assert (root / "datasets/safe/trade-upgrade.manifest.json").is_file()


def test_event_intelligence_binding_is_preserved_in_catalog_index(tmp_path) -> None:
    root = _bootstrap_root(tmp_path)
    run = tmp_path / "RUN_MANIFEST.json"
    value = _manifest(
        family="external_events",
        reconciliation="UNAVAILABLE",
        dataset_id="event-partial",
    )
    value["event_intelligence"] = {
        "schema": "alina.event_intelligence_integration.v1",
        "idea_count": 120,
        "coverage_complete": True,
        "coverage_sha256": "c" * 64,
        "linked_strategy_families": [
            "arbitrage",
            "copy_vault",
            "cross_venue_dislocation",
            "lead_lag",
        ],
        "dataset_families": ["external_events"],
        "proof_state": "STRUCTURAL_ONLY",
        "proof_of_pnl_allowed": False,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    _write_run(run, [value])

    result = index_run_manifests([run], root=root)
    assert result["active_data_status"] == "PARTIAL"
    [row] = json.loads((root / "catalog/DATA_INDEX.json").read_text())["shards"]
    assert row["event_intelligence_idea_count"] == 120
    assert row["event_intelligence_coverage_sha256"] == "c" * 64
    assert row["linked_strategy_families"] == [
        "arbitrage",
        "copy_vault",
        "cross_venue_dislocation",
        "lead_lag",
    ]



def test_index_migrates_preexisting_trade_digests_into_manifest_only(tmp_path):
    root = _bootstrap_root(tmp_path)
    manifest_dir = root / "datasets" / "safe"
    digest = "a" * 64
    proof = {
        "dataset_id": "old-trades", "sha256": digest,
        "trade_identity_digests": ["b" * 64, "c" * 64],
        "trade_identity_digests_exact": True,
    }
    (manifest_dir / "old-trades.manifest.json").write_text(json.dumps(proof))
    idx = root / "catalog" / "DATA_INDEX.json"
    row = {
        "dataset_id": "old-trades", "manifest_path": "datasets/safe/old-trades.manifest.json",
        "family": "trades", "venue": "bybit", "quality_status": "SAFE",
        "trade_identity_digests": ["b" * 64, "c" * 64],
        "trade_identity_digests_exact": True, "sha256": digest,
    }
    idx.write_text(json.dumps({"shards": [row], "active_data_status": "SAFE"}))
    index_run_manifests([], root=root)
    on_disk = json.loads(idx.read_text())
    assert len(on_disk["shards"]) == 1
    assert "trade_identity_digests" not in on_disk["shards"][0]
    assert on_disk["shards"][0]["trade_identity_digests_exact"] is True
    assert json.loads((manifest_dir / "old-trades.manifest.json").read_text())["trade_identity_digests"] == proof["trade_identity_digests"]
    assert "\n  " not in idx.read_text()


def test_compacted_index_preserves_selectors_and_scalar_integrity():
    from index_run_manifest import _compact_index_row
    row = {
        "dataset_id": "x", "quality_status": "SAFE", "release_tag": "data-v2-x",
        "sha256": "a" * 64, "bytes": 99, "event_count": 10,
        "quality_reasons": ["UNVERIFIED"], "trade_identity_digests": ["b" * 64],
        "release_container_asset": None, "gap_count": 4,
    }
    compact = _compact_index_row(row)
    assert compact["quality_status"] == "SAFE"
    assert compact["release_tag"] == "data-v2-x"
    assert compact["sha256"] == "a" * 64
    assert compact["gap_count"] == 4
    assert "trade_identity_digests" not in compact
    assert "quality_reasons" not in compact
    assert "release_container_asset" not in compact



def test_index_drops_only_redudant_scalars_and_keeps_cryptographic_locator():
    from index_run_manifest import _compact_index_row
    direct = {
        "dataset_id": "one", "quality_status": "SAFE",
        "release_repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
        "release_tag": "data-v2-direct", "release_asset": "one.jsonl.gz",
        "sha256": "a" * 64, "bytes": 100, "event_count": 7,
        "record_count": 7, "trade_count": 0, "trade_count_exact": False,
        "unique_trade_count_exact": False,
        "trade_identity_digests_exact": False,
        "duplicate_count": 0, "gap_count": 0,
        "release_remote_size": 100,
        "release_remote_digest": "sha256:" + "a" * 64,
        "replay_compatible": True,
    }
    shrunk = _compact_index_row(direct)
    assert shrunk["quality_status"] == "SAFE"
    assert shrunk["sha256"] == "a" * 64
    assert shrunk["gap_count"] == 0
    assert shrunk["replay_compatible"] is True
    for key in ("record_count", "trade_count", "trade_count_exact",
                "unique_trade_count_exact", "trade_identity_digests_exact",
                "duplicate_count", "release_remote_size", "release_remote_digest"):
        assert key not in shrunk
    packed = {
        **direct, "release_storage": "zip_entry",
        "release_asset": "one.jsonl.gz",
        "release_member": "one.jsonl.gz",
        "release_container_asset": "packed-shards-0000.zip",
        "release_remote_size": 1000,
        "release_remote_digest": "sha256:" + "b" * 64,
    }
    packed_row = _compact_index_row(packed)
    assert packed_row["release_storage"] == "zip_entry"
    assert packed_row["release_container_asset"] == "packed-shards-0000.zip"
    assert packed_row["release_remote_size"] == 1000
    assert packed_row["release_remote_digest"] == "sha256:" + "b" * 64
    assert "release_member" not in packed_row



def test_lossless_existing_index_repo_compaction(tmp_path):
    from index_run_manifest import (
        compact_existing_index, hydrate_default_release_repository
    )
    root = _bootstrap_root(tmp_path)
    path = root / "catalog/DATA_INDEX.json"
    baseline = json.loads(path.read_text(encoding="utf-8"))
    repo = "Rapt0r06300/hyperliquid-smart-wallet-observer"
    baseline["shards"] = [{
        "dataset_id": "historical-one", "quality_status": "PARTIAL",
        "release_repository": repo, "release_tag": "a",
        "release_asset": "evidence.jsonl.gz", "sha256": "a" * 64,
        "bytes": 50, "event_count": 3,
    }]
    path.write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    result = compact_existing_index(root)
    assert result["saved_bytes"] > 0
    compact = json.loads(path.read_text(encoding="utf-8"))
    assert compact["release_repository_default"] == repo
    assert "release_repository" not in compact["shards"][0]
    assert hydrate_default_release_repository(compact)[0]["release_repository"] == repo

    # Repeatability: after a prior migration, byte content cannot drift.
    migrated = path.read_bytes()
    compact_existing_index(root)
    assert path.read_bytes() == migrated


def test_compaction_refuses_noncanonical_release_repository(tmp_path):
    from index_run_manifest import compact_existing_index
    root = _bootstrap_root(tmp_path)
    path = root / "catalog/DATA_INDEX.json"
    original = json.loads(path.read_text(encoding="utf-8"))
    original["shards"] = [
        {"dataset_id": "foreign", "release_repository": "another/repo"}
    ]
    path.write_text(json.dumps(original), encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="CANONICAL"):
        compact_existing_index(root)


def test_index_size_failure_never_mutates_existing_manifests(tmp_path, monkeypatch):
    import pytest
    import index_run_manifest as module

    root = _bootstrap_root(tmp_path)
    old = root / "datasets/quarantine/same-id.manifest.json"
    old_payload = {"dataset_id": "same-id", "quality_status": "PARTIAL",
                   "sha256": "a" * 64}
    old.write_text(json.dumps(old_payload), encoding="utf-8")
    index_path = root / "catalog/DATA_INDEX.json"
    original_index = index_path.read_bytes()
    original_catalog = (root / "catalog/DATA_CATALOG.json").read_bytes()
    original_registry = (root / "catalog/DATA_QUALITY_REGISTRY.json").read_bytes()

    run = tmp_path / "RUN_MANIFEST.json"
    _write_run(run, [_manifest(family="l2Book",
                               reconciliation="SOURCE_CONTINUITY_VERIFIED",
                               dataset_id="same-id")])
    real_writer = module._atomic_json

    def reject_oversize_index(path, payload):
        if Path(path).name == "DATA_INDEX.json":
            raise ValueError("DATA_INDEX_TOO_LARGE: index mutation not published")
        return real_writer(path, payload)

    monkeypatch.setattr(module, "_atomic_json", reject_oversize_index)
    with pytest.raises(ValueError, match="DATA_INDEX_TOO_LARGE"):
        module.index_run_manifests([run], root=root)

    assert old.read_text(encoding="utf-8") == json.dumps(old_payload)
    assert not (root / "datasets/safe/same-id.manifest.json").exists()
    assert index_path.read_bytes() == original_index
    assert (root / "catalog/DATA_CATALOG.json").read_bytes() == original_catalog
    assert (root / "catalog/DATA_QUALITY_REGISTRY.json").read_bytes() == original_registry


def test_index_loads_trade_patch_files_once_per_batch(tmp_path, monkeypatch):
    """Large Release imports must not reread entire count patches per shard."""
    root = _bootstrap_root(tmp_path)
    catalog = root / "catalog"
    entries = [
        _manifest(family="trades", reconciliation="SOURCE_CONTINUITY_VERIFIED",
                  dataset_id="trade-patch-1"),
        _manifest(family="trades", reconciliation="SOURCE_CONTINUITY_VERIFIED",
                  dataset_id="trade-patch-2"),
    ]
    for i, manifest in enumerate(entries, start=1):
        manifest["unique_trade_count_exact"] = False
        manifest["unique_trade_count"] = None

    trade_patch = catalog / "TRADE_COUNT_PATCH.json"
    unique_patch = catalog / "TRADE_UNIQUE_COUNT_PATCH.json"
    trade_patch.write_text(json.dumps({"counts": {
        m["dataset_id"]: {
            "asset_sha256": m["sha256"], "trade_count": 10 + i,
            "trade_count_exact": True,
            "unique_identity_method": "full_native_or_deterministic_composite_string_v3",
        } for i, m in enumerate(entries)
    }}), encoding="utf-8")
    unique_patch.write_text(json.dumps({"counts": {
        m["dataset_id"]: {
            "asset_sha256": m["sha256"],
            "trade_count_scanned": 10 + i,
            "unique_trade_count": 10 + i,
            "unique_trade_count_exact": True,
        } for i, m in enumerate(entries)
    }}), encoding="utf-8")
    run = tmp_path / "RUN_MANIFEST.json"
    _write_run(run, entries)

    reads = {"TRADE_COUNT_PATCH.json": 0, "TRADE_UNIQUE_COUNT_PATCH.json": 0}
    original = Path.read_text
    def tracked(path, *args, **kwargs):
        if path.name in reads:
            reads[path.name] += 1
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", tracked)

    index_run_manifests([run], root=root)
    assert reads["TRADE_COUNT_PATCH.json"] == 1
    assert reads["TRADE_UNIQUE_COUNT_PATCH.json"] == 1
    rows = json.loads((catalog / "DATA_INDEX.json").read_text())["shards"]
    assert [r["trade_count"] for r in rows] == [10, 11]
    assert [r["unique_trade_count"] for r in rows] == [10, 11]

def test_index_drops_duplicate_diagnostics_only_when_sha_receipt_matches(tmp_path):
    root = _bootstrap_root(tmp_path)
    run = tmp_path / "RUN_MANIFEST.json"
    _write_run(run, [_manifest(
        family="trades",
        reconciliation="SOURCE_CONTINUITY_VERIFIED",
        dataset_id="sha-backed-diagnostics",
    )])
    index_run_manifests([run], root=root)
    index_file = root / "catalog/DATA_INDEX.json"
    result = json.loads(index_file.read_text(encoding="utf-8"))
    [row] = result["shards"]
    receipt = json.loads((root / row["manifest_path"]).read_text(encoding="utf-8"))

    assert row["replay_compatible"] is True
    assert row["quality_status"] == "SAFE"
    assert row["sha256"] == receipt["sha256"]
    assert row["source"] == "bybit_public_ws"
    assert "replay_schema_version" not in row
    assert "replay_reason" not in row
    assert receipt["source"] == "bybit_public_ws"
    assert receipt["replay_schema_version"] == "alina.replay.v1"
    assert receipt["replay_reason"] == "SMOKE_OK"
    original_index = index_file.read_bytes()
    index_run_manifests([], root=root)
    assert index_file.read_bytes() == original_index


def test_index_preserves_unbacked_diagnostics_when_receipt_hash_mismatch(tmp_path):
    root = _bootstrap_root(tmp_path)
    path = root / "catalog/DATA_INDEX.json"
    original = json.loads(path.read_text(encoding="utf-8"))
    row = {
        "dataset_id": "old-diagnostic",
        "family": "trades",
        "venue": "bybit",
        "quality_status": "PARTIAL",
        "sha256": "a" * 64,
        "manifest_path": "datasets/quarantine/old-diagnostic.manifest.json",
        "source": "old_source",
        "replay_schema_version": "alina.replay.v1",
        "replay_reason": "PROOF_PENDING",
    }
    original["shards"] = [row]
    path.write_text(json.dumps(original), encoding="utf-8")
    receipt = root / row["manifest_path"]
    receipt.write_text(json.dumps({
        **row, "sha256": "b" * 64,
    }), encoding="utf-8")

    index_run_manifests([], root=root)
    [reindexed] = json.loads(path.read_text(encoding="utf-8"))["shards"]
    assert reindexed["source"] == "old_source"
    assert reindexed["replay_schema_version"] == "alina.replay.v1"
    assert reindexed["replay_reason"] == "PROOF_PENDING"


def test_sha_bound_size_compaction_never_drops_unproven_values():
    from index_run_manifest import _compact_index_row, _size_proof_matches
    row = {
        "dataset_id": "one",
        "sha256": "a" * 64,
        "uncompressed_bytes": 1200,
        "uncompressed_size_exact": True,
        "event_count": 12,
    }
    verified = {
        "one": {"asset_sha256": "a" * 64, "uncompressed_bytes": 1200}
    }
    assert _size_proof_matches(row, verified)
    compact = _compact_index_row(row, size_patch_proven=True)
    assert "uncompressed_bytes" not in compact
    assert "uncompressed_size_exact" not in compact
    assert compact["sha256"] == row["sha256"]
    for invalid in (
        {"one": {"asset_sha256": "b" * 64, "uncompressed_bytes": 1200}},
        {"one": {"asset_sha256": "a" * 64, "uncompressed_bytes": 2000}},
        {},
    ):
        assert _size_proof_matches(row, invalid) is False
        kept = _compact_index_row(row, size_patch_proven=False)
        assert kept["uncompressed_bytes"] == 1200
        assert kept["uncompressed_size_exact"] is True

def test_index_factors_verified_homogeneous_run_manifest_tags_without_loss(tmp_path):
    from index_run_manifest import hydrate_default_release_repository
    root = _bootstrap_root(tmp_path)
    run = tmp_path / "RUN_MANIFEST.json"
    manifests = [
        _manifest(family="trades", reconciliation="SOURCE_CONTINUITY_VERIFIED",
                  dataset_id=name)
        for name in ("first", "second")
    ]
    for manifest in manifests:
        manifest["release"]["tag"] = "data-v2-physical-part"
    _write_run(run, manifests)
    index_run_manifests([run], root=root)
    index_path = root / "catalog/DATA_INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["run_manifest_release_tags_by_release"] == {
        "data-v2-physical-part": "data-v2-run-1-1-native"
    }
    assert all("run_manifest_release_tag" not in row for row in index["shards"])
    hydrated = hydrate_default_release_repository(index)
    assert all(row["run_manifest_release_tag"] == "data-v2-run-1-1-native"
               for row in hydrated)
    assert all(row["release_tag"] == "data-v2-physical-part" for row in hydrated)
    original_bytes = index_path.read_bytes()
    index_run_manifests([], root=root)
    assert index_path.read_bytes() == original_bytes


def test_index_preserves_conflicting_run_manifest_tag_aliases(tmp_path):
    root = _bootstrap_root(tmp_path)
    manifests = [
        _manifest(family="trades", reconciliation="SOURCE_CONTINUITY_VERIFIED",
                  dataset_id=name)
        for name in ("one", "two")
    ]
    for manifest in manifests:
        manifest["release"]["tag"] = "data-v2-physical-part"
    paths = []
    for i, manifest in enumerate(manifests):
        run = tmp_path / f"RUN_MANIFEST-{i}.json"
        _write_run(run, [manifest])
        body = json.loads(run.read_text(encoding="utf-8"))
        body["release_tag"] = f"data-v2-canonical-{i}"
        run.write_text(json.dumps(body), encoding="utf-8")
        paths.append(run)
    index_run_manifests(paths, root=root)
    index = json.loads((root / "catalog/DATA_INDEX.json").read_text())
    assert "run_manifest_release_tags_by_release" not in index
    assert {row["run_manifest_release_tag"] for row in index["shards"]} == {
        "data-v2-canonical-0", "data-v2-canonical-1"
    }

def test_repeated_collection_run_ids_are_reversibly_factored(tmp_path):
    from index_run_manifest import hydrate_default_release_repository, compact_existing_index
    root = _bootstrap_root(tmp_path)
    run = tmp_path / "RUN_MANIFEST.json"
    manifests = [
        _manifest(family="trades", reconciliation="SOURCE_CONTINUITY_VERIFIED",
                  dataset_id=dataset_id)
        for dataset_id in ("same-run-first", "same-run-second")
    ]
    for manifest in manifests:
        manifest["collection_run_id"] = "run-shared-123"
    _write_run(run, manifests)
    index_run_manifests([run], root=root)
    index_path = root / "catalog/DATA_INDEX.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert index["collection_run_ids_by_release"] == {
        "data-v2-run-1-1-native": "run-shared-123"
    }
    assert all("collection_run_id" not in row for row in index["shards"])
    expanded = hydrate_default_release_repository(index)
    assert [row["collection_run_id"] for row in expanded] == [
        "run-shared-123", "run-shared-123"
    ]
    original = index_path.read_bytes()
    compact_existing_index(root)
    assert index_path.read_bytes() == original


def test_mixed_collection_run_ids_stay_explicit_and_conflicts_fail_closed(tmp_path):
    import pytest
    from index_run_manifest import hydrate_default_release_repository
    root = _bootstrap_root(tmp_path)
    run = tmp_path / "RUN_MANIFEST.json"
    manifests = [
        _manifest(family="trades", reconciliation="SOURCE_CONTINUITY_VERIFIED",
                  dataset_id=dataset_id)
        for dataset_id in ("different-run-first", "different-run-second")
    ]
    manifests[0]["collection_run_id"] = "run-a"
    manifests[1]["collection_run_id"] = "run-b"
    _write_run(run, manifests)
    index_run_manifests([run], root=root)
    index = json.loads((root / "catalog/DATA_INDEX.json").read_text(encoding="utf-8"))
    assert "collection_run_ids_by_release" not in index
    assert {row["collection_run_id"] for row in index["shards"]} == {"run-a", "run-b"}
    index["collection_run_ids_by_release"] = {"data-v2-run-1-1-native": "forged"}
    with pytest.raises(ValueError, match="conflicting canonical collection run ID"):
        hydrate_default_release_repository(index)


def test_measurement_writers_keep_index_alias_factorization():
    """Round-trip expanded rows from backfills without duplicating huge fields."""
    from index_run_manifest import (
        CANONICAL_DATA_REPOSITORY, compact_index_rows,
        hydrate_default_release_repository,
    )
    row = {
        "dataset_id": "trade-a", "release_repository": CANONICAL_DATA_REPOSITORY,
        "release_tag": "data-v2-shared", "run_manifest_release_tag": "data-v2-run",
        "collection_run_id": "run-repeated", "quality_status": "SAFE",
        "sha256": "a" * 64, "event_count": 10,
    }
    other = {**row, "dataset_id": "trade-b", "sha256": "b" * 64}
    index = {"shards": [row, other], "release_repository_default": CANONICAL_DATA_REPOSITORY}
    original = [dict(row), dict(other)]
    for _ in range(3):
        index["shards"] = compact_index_rows(
            index, hydrate_default_release_repository(index)
        )
        assert all("collection_run_id" not in r for r in index["shards"])
        assert all("run_manifest_release_tag" not in r for r in index["shards"])
        assert all("release_repository" not in r for r in index["shards"])
        assert index["run_manifest_release_tags_by_release"] == {
            "data-v2-shared": "data-v2-run"
        }
        assert index["collection_run_ids_by_release"] == {
            "data-v2-shared": "run-repeated"
        }
        assert hydrate_default_release_repository(index) == original
