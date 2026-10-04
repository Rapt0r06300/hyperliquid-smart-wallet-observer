from __future__ import annotations

import json
from pathlib import Path

from tools.build_catalog_metrics import build

ROOT = Path(__file__).resolve().parents[1]


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
