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
