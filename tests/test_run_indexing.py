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
    assert row["release_repository"] == "Rapt0r06300/hyperliquid-smart-wallet-observer"
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
