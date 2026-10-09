from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from tools.build_catalog_metrics import build

ROOT = Path(__file__).resolve().parents[1]


def test_verify_metrics_source_rejects_stale_index_even_when_schema_is_valid(tmp_path):
    import tools.build_catalog_metrics as metrics

    index_path = tmp_path / "DATA_INDEX.json"
    metrics_path = tmp_path / "DATA_METRICS.json"
    index_path.write_text(
        json.dumps({"shards": [{"dataset_id": "a"}, {"dataset_id": "b"}]}),
        encoding="utf-8",
    )
    metrics_path.write_text(
        json.dumps({
            "schema_version": "alina.data_metrics.v4",
            "source_index_sha256": hashlib.sha256(b'{"shards": []}').hexdigest(),
            "totals": {"TOTAL_SHARDS": 1},
        }),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="DATA_METRICS_STALE_INDEX"):
        metrics.verify_metrics_source(index_path, metrics_path)


def test_verify_metrics_source_accepts_exact_sha_and_shard_count(tmp_path):
    import tools.build_catalog_metrics as metrics

    index_path = tmp_path / "DATA_INDEX.json"
    metrics_path = tmp_path / "DATA_METRICS.json"
    index_path.write_text(
        json.dumps({"shards": [{"dataset_id": "a"}, {"dataset_id": "b"}]}),
        encoding="utf-8",
    )
    metrics_path.write_text(
        json.dumps({
            "schema_version": "alina.data_metrics.v4",
            "source_index_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
            "totals": {"TOTAL_SHARDS": 2},
        }),
        encoding="utf-8",
    )

    proof = metrics.verify_metrics_source(index_path, metrics_path)

    assert proof["total_shards"] == 2
    assert proof["source_index_sha256"] == hashlib.sha256(index_path.read_bytes()).hexdigest()


def test_metrics_file_is_machine_readable_and_counts_shards():
    out = build()
    idx = json.loads((ROOT / "catalog" / "DATA_INDEX.json").read_text())
    totals = out["totals"]
    assert totals["TOTAL_SHARDS"] == len(idx.get("shards") or [])
    assert "TOTAL_TRADES_COLLECTED" in totals
    assert "TOTAL_TRADES_REPLAYABLE" in totals
    assert "TRADE_SHARDS_WITH_EXACT_COUNT" in totals
    assert "TRADE_SHARDS_MISSING_EXACT_COUNT" in totals
    assert "TOTAL_TRADES_COUNT_COVERAGE_COMPLETE" in totals
    assert out["schema_version"] == "alina.data_metrics.v4"


def test_trade_totals_never_zero_fill_unknown_legacy_counts(tmp_path, monkeypatch):
    import tools.build_catalog_metrics as metrics

    root = tmp_path
    catalog = root / "catalog"
    catalog.mkdir()
    (catalog / "DATA_INDEX.json").write_text(
        json.dumps({
            "shards": [
                {
                    "dataset_id": "legacy-trades",
                    "family": "trades",
                    "venue": "x",
                    "symbol": "BTC",
                    "quality_status": "SAFE",
                    "event_count": 10,
                    "trade_count": 0,
                    "trade_count_exact": False,
                    "replay_compatible": False,
                    "bytes": 100,
                },
                {
                    "dataset_id": "exact-trades",
                    "family": "trades",
                    "venue": "x",
                    "symbol": "BTC",
                    "quality_status": "SAFE",
                    "event_count": 5,
                    "trade_count": 7,
                    "trade_count_exact": True,
                    "unique_trade_count": 6,
                    "unique_trade_count_exact": True,
                    "replay_compatible": True,
                    "bytes": 50,
                    "uncompressed_bytes": 125,
                    "uncompressed_size_exact": True,
                    "trade_identity_digests": ["a" * 64] * 6,
                    "trade_identity_digests_exact": False,
                },
            ]
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(metrics, "INDEX", catalog / "DATA_INDEX.json")
    monkeypatch.setattr(metrics, "METRICS", catalog / "DATA_METRICS.json")
    out = metrics.build()["totals"]
    assert out["TOTAL_TRADES_COLLECTED"] == 7
    assert out["TRADE_SHARDS_MISSING_EXACT_COUNT"] == 1
    assert out["TOTAL_TRADES_COUNT_COVERAGE_COMPLETE"] is False
    assert out["TOTAL_UNIQUE_TRADES_WITHIN_SHARDS"] == 6



def test_metrics_restore_sha_matched_exact_counts_and_reject_stale_bybit_unique(tmp_path, monkeypatch):
    import tools.build_catalog_metrics as metrics

    catalog = tmp_path / "catalog"
    catalog.mkdir()
    sha = "a" * 64
    (catalog / "DATA_INDEX.json").write_text(
        json.dumps({
            "shards": [{
                "dataset_id": "bybit-archive",
                "family": "trades",
                "venue": "bybit",
                "symbol": "BTCUSDT",
                "quality_status": "PARTIAL",
                "event_count": 190000,
                "trade_count": 0,
                "trade_count_exact": False,
                "unique_trade_count": 138698,
                "unique_trade_count_exact": True,
                "replay_compatible": False,
                "sha256": sha,
                "bytes": 100,
            }]
        }),
        encoding="utf-8",
    )
    (catalog / "TRADE_COUNT_PATCH.json").write_text(
        json.dumps({
            "counts": {
                "bybit-archive": {
                    "asset_sha256": sha,
                    "trade_count": 190000,
                    "trade_count_exact": True,
                    "unique_trade_count": 138698,
                    "unique_trade_count_exact": True,
                    "unique_identity_method": "full_native_or_deterministic_composite_string_v2",
                }
            },
            "failure_reasons": {},
        }),
        encoding="utf-8",
    )
    (catalog / "TRADE_UNIQUE_COUNT_PATCH.json").write_text(
        json.dumps({
            "coverage_complete": True,
            "global_unique_trade_count": 138698,
            "global_identity_digest": "c" * 64,
            "identity_version": "native-id-or-venue-family-symbol-time-side-price-size-v2-full-string",
            "failure_reasons": {},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(metrics, "INDEX", catalog / "DATA_INDEX.json")
    monkeypatch.setattr(metrics, "METRICS", catalog / "DATA_METRICS.json")
    monkeypatch.setattr(metrics, "TRADE_COUNT_PATCH", catalog / "TRADE_COUNT_PATCH.json")
    monkeypatch.setattr(metrics, "UNIQUE_PATCH", catalog / "TRADE_UNIQUE_COUNT_PATCH.json")
    monkeypatch.setattr(metrics, "RECORD_PATCH", catalog / "missing-records.json")
    monkeypatch.setattr(metrics, "UNCOMPRESSED_PATCH", catalog / "missing-sizes.json")

    totals = metrics.build()["totals"]
    assert totals["TOTAL_TRADES_COLLECTED"] == 190000
    assert totals["TRADE_SHARDS_WITH_EXACT_COUNT"] == 1
    assert totals["TRADE_SHARDS_MISSING_EXACT_COUNT"] == 0
    assert totals["TOTAL_UNIQUE_TRADES_WITHIN_SHARDS"] == 0
    assert totals["TOTAL_UNIQUE_TRADES_GLOBAL"] is None
    assert totals["GLOBAL_UNIQUE_TRADES_COVERAGE_COMPLETE"] is False


def test_metrics_ignore_trade_patch_when_asset_sha_does_not_match(tmp_path, monkeypatch):
    import tools.build_catalog_metrics as metrics

    catalog = tmp_path / "catalog"
    catalog.mkdir()
    (catalog / "DATA_INDEX.json").write_text(
        json.dumps({
            "shards": [{
                "dataset_id": "trade",
                "family": "trades",
                "venue": "x",
                "symbol": "BTC",
                "quality_status": "PARTIAL",
                "event_count": 10,
                "trade_count": 0,
                "trade_count_exact": False,
                "unique_trade_count_exact": False,
                "replay_compatible": False,
                "sha256": "a" * 64,
                "bytes": 10,
            }]
        }),
        encoding="utf-8",
    )
    (catalog / "TRADE_COUNT_PATCH.json").write_text(
        json.dumps({"counts": {
            "trade": {
                "asset_sha256": "b" * 64,
                "trade_count": 999,
                "trade_count_exact": True,
            }
        }}),
        encoding="utf-8",
    )
    monkeypatch.setattr(metrics, "INDEX", catalog / "DATA_INDEX.json")
    monkeypatch.setattr(metrics, "METRICS", catalog / "DATA_METRICS.json")
    monkeypatch.setattr(metrics, "TRADE_COUNT_PATCH", catalog / "TRADE_COUNT_PATCH.json")
    monkeypatch.setattr(metrics, "RECORD_PATCH", catalog / "missing-records.json")
    monkeypatch.setattr(metrics, "UNCOMPRESSED_PATCH", catalog / "missing-sizes.json")
    monkeypatch.setattr(metrics, "UNIQUE_PATCH", catalog / "missing-unique.json")

    totals = metrics.build()["totals"]
    assert totals["TOTAL_TRADES_COLLECTED"] == 0
    assert totals["TRADE_SHARDS_MISSING_EXACT_COUNT"] == 1



def test_metrics_reject_v3_global_unique_patch_that_did_not_cover_all_trade_shards(tmp_path, monkeypatch):
    import tools.build_catalog_metrics as metrics

    catalog = tmp_path / "catalog"
    catalog.mkdir()
    (catalog / "DATA_INDEX.json").write_text(
        json.dumps({
            "shards": [
                {
                    "dataset_id": "a",
                    "family": "trades",
                    "venue": "x",
                    "symbol": "BTC",
                    "quality_status": "PARTIAL",
                    "event_count": 1,
                    "trade_count": 1,
                    "trade_count_exact": True,
                    "unique_trade_count": 1,
                    "unique_trade_count_exact": True,
                    "replay_compatible": False,
                    "sha256": "a" * 64,
                    "bytes": 1,
                },
                {
                    "dataset_id": "b",
                    "family": "trades",
                    "venue": "x",
                    "symbol": "ETH",
                    "quality_status": "PARTIAL",
                    "event_count": 1,
                    "trade_count": 1,
                    "trade_count_exact": True,
                    "unique_trade_count": 1,
                    "unique_trade_count_exact": True,
                    "replay_compatible": False,
                    "sha256": "b" * 64,
                    "bytes": 1,
                },
            ]
        }),
        encoding="utf-8",
    )
    (catalog / "TRADE_UNIQUE_COUNT_PATCH.json").write_text(
        json.dumps({
            "identity_version": metrics.GLOBAL_IDENTITY_VERSION,
            "coverage_complete": True,
            "trade_shards_in_scope": 1,
            "unproven_trade_count_shards": 0,
            "global_unique_trade_count": 1,
            "global_identity_digest": "d" * 64,
            "failure_reasons": {},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(metrics, "INDEX", catalog / "DATA_INDEX.json")
    monkeypatch.setattr(metrics, "METRICS", catalog / "DATA_METRICS.json")
    monkeypatch.setattr(metrics, "UNIQUE_PATCH", catalog / "TRADE_UNIQUE_COUNT_PATCH.json")
    monkeypatch.setattr(metrics, "TRADE_COUNT_PATCH", catalog / "missing-trade-patch.json")
    monkeypatch.setattr(metrics, "RECORD_PATCH", catalog / "missing-records.json")
    monkeypatch.setattr(metrics, "UNCOMPRESSED_PATCH", catalog / "missing-sizes.json")

    totals = metrics.build()["totals"]
    assert totals["TOTAL_UNIQUE_TRADES_GLOBAL"] is None
    assert totals["GLOBAL_UNIQUE_TRADES_COVERAGE_COMPLETE"] is False



def test_metrics_uses_current_global_unique_patch_for_bybit_per_shard_unique(tmp_path, monkeypatch):
    import tools.build_catalog_metrics as metrics

    catalog = tmp_path / "catalog"
    catalog.mkdir()
    sha = "a" * 64
    (catalog / "DATA_INDEX.json").write_text(
        json.dumps({
            "shards": [{
                "dataset_id": "bybit-archive",
                "family": "trades",
                "venue": "bybit",
                "symbol": "BTCUSDT",
                "quality_status": "PARTIAL",
                "event_count": 190000,
                "trade_count": 190000,
                "trade_count_exact": True,
                "unique_trade_count": 138698,
                "unique_trade_count_exact": True,
                "replay_compatible": False,
                "sha256": sha,
                "bytes": 100,
            }]
        }),
        encoding="utf-8",
    )
    (catalog / "TRADE_COUNT_PATCH.json").write_text(
        json.dumps({
            "counts": {
                "bybit-archive": {
                    "asset_sha256": sha,
                    "trade_count": 190000,
                    "trade_count_exact": True,
                    "unique_trade_count": 138698,
                    "unique_trade_count_exact": True,
                    "unique_identity_method": "full_native_or_deterministic_composite_string_v2",
                }
            },
            "failure_reasons": {},
        }),
        encoding="utf-8",
    )
    (catalog / "TRADE_UNIQUE_COUNT_PATCH.json").write_text(
        json.dumps({
            "identity_version": metrics.GLOBAL_IDENTITY_VERSION,
            "coverage_complete": True,
            "candidate_trade_shards": 1,
            "successful": 1,
            "remaining_candidate_shards": 0,
            "failed": [],
            "global_unique_trade_count": 190000,
            "global_identity_digest": "c" * 64,
            "cross_shard_overlap_count": 0,
            "failure_reasons": {},
            "counts": {
                "bybit-archive": {
                    "trade_count_scanned": 190000,
                    "unique_trade_count": 190000,
                    "unique_trade_count_exact": True,
                }
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(metrics, "INDEX", catalog / "DATA_INDEX.json")
    monkeypatch.setattr(metrics, "METRICS", catalog / "DATA_METRICS.json")
    monkeypatch.setattr(metrics, "TRADE_COUNT_PATCH", catalog / "TRADE_COUNT_PATCH.json")
    monkeypatch.setattr(metrics, "UNIQUE_PATCH", catalog / "TRADE_UNIQUE_COUNT_PATCH.json")
    monkeypatch.setattr(metrics, "RECORD_PATCH", catalog / "missing-records.json")
    monkeypatch.setattr(metrics, "UNCOMPRESSED_PATCH", catalog / "missing-sizes.json")

    totals = metrics.build()["totals"]
    assert totals["TOTAL_TRADES_COLLECTED"] == 190000
    assert totals["TOTAL_UNIQUE_TRADES_WITHIN_SHARDS"] == 190000
    assert totals["TRADE_SHARDS_WITH_EXACT_UNIQUE_COUNT"] == 1
    assert totals["TRADE_SHARDS_MISSING_EXACT_UNIQUE_COUNT"] == 0
    assert totals["TOTAL_UNIQUE_TRADES_GLOBAL"] == 190000
    assert totals["GLOBAL_UNIQUE_TRADES_COVERAGE_COMPLETE"] is True
    assert totals["TOTAL_UNIQUE_TRADES_COVERAGE_COMPLETE"] is True



def test_metrics_rejects_v3_unique_row_when_scanned_trade_count_mismatches(tmp_path, monkeypatch):
    import tools.build_catalog_metrics as metrics

    catalog = tmp_path / "catalog"
    catalog.mkdir()
    sha = "a" * 64
    (catalog / "DATA_INDEX.json").write_text(
        json.dumps({"shards": [{
            "dataset_id": "bybit-archive",
            "family": "trades",
            "venue": "bybit",
            "symbol": "BTCUSDT",
            "quality_status": "PARTIAL",
            "event_count": 10,
            "trade_count": 10,
            "trade_count_exact": True,
            "unique_trade_count": 5,
            "unique_trade_count_exact": True,
            "replay_compatible": False,
            "sha256": sha,
            "bytes": 10,
        }]}),
        encoding="utf-8",
    )
    (catalog / "TRADE_COUNT_PATCH.json").write_text(
        json.dumps({"counts": {
            "bybit-archive": {
                "asset_sha256": sha,
                "trade_count": 10,
                "trade_count_exact": True,
                "unique_trade_count": 5,
                "unique_trade_count_exact": True,
                "unique_identity_method": "full_native_or_deterministic_composite_string_v2",
            }
        }}),
        encoding="utf-8",
    )
    (catalog / "TRADE_UNIQUE_COUNT_PATCH.json").write_text(
        json.dumps({
            "identity_version": metrics.GLOBAL_IDENTITY_VERSION,
            "coverage_complete": True,
            "candidate_trade_shards": 1,
            "successful": 1,
            "remaining_candidate_shards": 0,
            "failed": [],
            "global_unique_trade_count": 10,
            "global_identity_digest": "d" * 64,
            "counts": {
                "bybit-archive": {
                    "trade_count_scanned": 9,
                    "unique_trade_count": 9,
                    "unique_trade_count_exact": True,
                }
            },
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(metrics, "INDEX", catalog / "DATA_INDEX.json")
    monkeypatch.setattr(metrics, "METRICS", catalog / "DATA_METRICS.json")
    monkeypatch.setattr(metrics, "TRADE_COUNT_PATCH", catalog / "TRADE_COUNT_PATCH.json")
    monkeypatch.setattr(metrics, "UNIQUE_PATCH", catalog / "TRADE_UNIQUE_COUNT_PATCH.json")
    monkeypatch.setattr(metrics, "RECORD_PATCH", catalog / "missing-records.json")
    monkeypatch.setattr(metrics, "UNCOMPRESSED_PATCH", catalog / "missing-sizes.json")

    totals = metrics.build()["totals"]
    assert totals["TOTAL_TRADES_COLLECTED"] == 10
    assert totals["TOTAL_UNIQUE_TRADES_WITHIN_SHARDS"] == 0
    assert totals["TRADE_SHARDS_MISSING_EXACT_UNIQUE_COUNT"] == 1
    assert totals["TOTAL_UNIQUE_TRADES_COVERAGE_COMPLETE"] is False



def test_compact_index_restores_exact_trade_identities_from_sha_bound_manifest(tmp_path, monkeypatch):
    import tools.build_catalog_metrics as metrics
    root = tmp_path
    catalog = root / "catalog"
    catalog.mkdir()
    folder = root / "datasets" / "safe"
    folder.mkdir(parents=True)
    sha = "a" * 64
    digest_a, digest_b = "b" * 64, "c" * 64
    manifest = {
        "dataset_id": "compact-trades", "sha256": sha,
        "trade_identity_digests_exact": True,
        "trade_identity_digests": [digest_a, digest_b],
    }
    path = folder / "compact-trades.manifest.json"
    path.write_text(json.dumps(manifest))
    idx = {
        "shards": [{
            "dataset_id": "compact-trades", "family": "trades",
            "venue": "binance", "symbol": "BTC", "quality_status": "SAFE",
            "event_count": 2, "record_count": 2, "trade_count": 2,
            "trade_count_exact": True, "unique_trade_count": 2,
            "unique_trade_count_exact": True,
            "trade_identity_digests_exact": True,
            "manifest_path": "datasets/safe/compact-trades.manifest.json",
            "sha256": sha, "bytes": 100, "replay_compatible": True,
        }]
    }
    (catalog / "DATA_INDEX.json").write_text(json.dumps(idx))
    monkeypatch.setattr(metrics, "ROOT", root)
    monkeypatch.setattr(metrics, "INDEX", catalog / "DATA_INDEX.json")
    monkeypatch.setattr(metrics, "METRICS", catalog / "DATA_METRICS.json")
    monkeypatch.setattr(metrics, "UNIQUE_PATCH", catalog / "missing-unique.json")
    monkeypatch.setattr(metrics, "TRADE_COUNT_PATCH", catalog / "missing-trades.json")
    monkeypatch.setattr(metrics, "RECORD_PATCH", catalog / "missing-records.json")
    monkeypatch.setattr(metrics, "UNCOMPRESSED_PATCH", catalog / "missing-sizes.json")
    assert metrics.build()["totals"]["GLOBAL_UNIQUE_TRADES_COVERAGE_COMPLETE"] is True

    # A manifest no longer matching the indexed hash cannot falsely certify
    # global uniqueness after index compaction.
    manifest["sha256"] = "d" * 64
    path.write_text(json.dumps(manifest))
    totals = metrics.build()["totals"]
    assert totals["GLOBAL_UNIQUE_TRADES_COVERAGE_COMPLETE"] is False
    assert totals["TOTAL_UNIQUE_TRADES_GLOBAL"] is None



def test_new_exact_shards_are_not_discarded_from_total_bytes_by_stale_patch(tmp_path, monkeypatch):
    import tools.build_catalog_metrics as metrics

    catalog = tmp_path / "catalog"
    catalog.mkdir()
    rows = []
    for dataset_id, size in (("old", 100), ("new", 300)):
        rows.append({
            "dataset_id": dataset_id, "family": "bbo",
            "venue": "okx", "symbol": "BTCUSDT",
            "quality_status": "SAFE", "event_count": 1,
            "record_count": 1, "bytes": 50,
            "uncompressed_bytes": size, "uncompressed_size_exact": True,
        })
    (catalog / "DATA_INDEX.json").write_text(json.dumps({"shards": rows}))
    (catalog / "UNCOMPRESSED_SIZE_PATCH.json").write_text(json.dumps({
        "coverage_complete": True, "sizes": {"old": {"uncompressed_bytes": 100}}
    }))
    monkeypatch.setattr(metrics, "ROOT", tmp_path)
    monkeypatch.setattr(metrics, "INDEX", catalog / "DATA_INDEX.json")
    monkeypatch.setattr(metrics, "METRICS", catalog / "DATA_METRICS.json")
    monkeypatch.setattr(metrics, "UNIQUE_PATCH", catalog / "absent-unique.json")
    monkeypatch.setattr(metrics, "TRADE_COUNT_PATCH", catalog / "absent-trades.json")
    monkeypatch.setattr(metrics, "RECORD_PATCH", catalog / "absent-records.json")
    monkeypatch.setattr(metrics, "UNCOMPRESSED_PATCH", catalog / "UNCOMPRESSED_SIZE_PATCH.json")
    totals = metrics.build()["totals"]
    assert totals["TOTAL_SHARDS"] == 2
    assert totals["TOTAL_UNCOMPRESSED_BYTES"] == 400
    assert totals["UNCOMPRESSED_SIZE_EXACT_ASSETS"] == 2
    assert totals["UNCOMPRESSED_SIZE_COVERAGE_COMPLETE"] is True


def test_gap_totals_use_original_sha_bound_manifest_not_a_fake_zero(tmp_path, monkeypatch):
    import tools.build_catalog_metrics as metrics
    import json
    root = tmp_path
    cat = root / "catalog"
    cat.mkdir()
    folder = root / "datasets" / "rejected"
    folder.mkdir(parents=True)
    sha = "a" * 64
    manifest = folder / "gap.manifest.json"
    manifest.write_text(json.dumps({"dataset_id": "gap", "sha256": sha, "integrity": {"gap_count": 7}}))
    (cat / "DATA_INDEX.json").write_text(json.dumps({"shards": [{
        "dataset_id": "gap", "sha256": sha, "manifest_path": "datasets/rejected/gap.manifest.json",
        "quality_status": "REJECT", "family": "l2Book", "venue": "okx", "symbol": "BTC",
        "bytes": 20, "event_count": 100
    }]}))
    monkeypatch.setattr(metrics, "ROOT", root)
    monkeypatch.setattr(metrics, "INDEX", cat / "DATA_INDEX.json")
    monkeypatch.setattr(metrics, "UNIQUE_PATCH", cat / "no-unique.json")
    monkeypatch.setattr(metrics, "TRADE_COUNT_PATCH", cat / "no-trades.json")
    monkeypatch.setattr(metrics, "RECORD_PATCH", cat / "no-records.json")
    monkeypatch.setattr(metrics, "UNCOMPRESSED_PATCH", cat / "no-sizes.json")
    totals = metrics.build()["totals"]
    assert totals["TOTAL_GAP_RECORDS"] == 7
    assert totals["GAP_COUNT_COVERAGE_COMPLETE"] is True
    manifest.write_text(json.dumps({"dataset_id": "gap", "sha256": "b" * 64, "integrity": {"gap_count": 7}}))
    totals = metrics.build()["totals"]
    assert totals["TOTAL_GAP_RECORDS"] == 0
    assert totals["GAP_COUNT_COVERAGE_COMPLETE"] is False
    assert totals["GAP_COUNT_MISSING_SHARDS"] == 1

