from __future__ import annotations

import json
from pathlib import Path

from tools.build_quarantine_audit import build


def _manifest(dataset_id: str, *, safe_now: bool) -> dict:
    manifest = {
        "dataset_id": dataset_id,
        "family": "trades",
        "venue": "bybit",
        "symbol": "BTCUSDT",
        "start_ts_ms": 1000,
        "end_ts_ms": 2000,
        "sha256": "a" * 64,
        "bytes": 100,
        "event_count": 10,
        "collector_version": "test",
        "source": "bybit_official_archive",
        "quality_status": "PARTIAL",
        "asset_verified": True,
        "validation_allowed": False,
        "replay_compatible": True,
        "replay_schema_version": "alina.replay.v2",
        "replay_reason": "STRICT_PARSE_CHRONOLOGY_OK",
        "trade_count": 10,
        "trade_count_exact": True,
        "unique_trade_count": 10,
        "unique_trade_count_exact": True,
        "provenance": {
            "public_data_only": True,
            "authenticated": False,
            "real_execution": False,
            "transports": ["https"],
            "timestamp_semantics": ["historical_exchange_time_only"],
        },
        "integrity": {
            "gap_count": 0,
            "regression_count": 0,
            "missing_timestamp_count": 0,
            "missing_monotonic_count": 10,
            "desync_count": 0,
            "duplicate_count": 0,
            "duplicates_deduped": True,
        },
        "reconciliation": {"status": "SOURCE_ARCHIVE_VERIFIED"},
        "quality_reasons": ["FATAL_INTEGRITY:missing_monotonic_count=10"],
    }
    if not safe_now:
        manifest["asset_verified"] = False
        manifest["quality_reasons"].append("ASSET_NOT_VERIFIED")
    return manifest


def test_quarantine_audit_finds_historical_live_only_false_quarantine(tmp_path: Path):
    catalog = tmp_path / "catalog"
    quarantine = tmp_path / "datasets" / "quarantine"
    catalog.mkdir()
    quarantine.mkdir(parents=True)
    first = _manifest("historical-live-only", safe_now=True)
    second = _manifest("historical-real-partial", safe_now=False)
    for manifest in (first, second):
        path = quarantine / f"{manifest['dataset_id']}.manifest.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")

    rows = []
    for manifest in (first, second):
        rows.append({
            "dataset_id": manifest["dataset_id"],
            "venue": manifest["venue"],
            "family": manifest["family"],
            "symbol": manifest["symbol"],
            "quality_status": "PARTIAL",
            "record_count": 10,
            "event_count": 10,
            "replay_compatible": True,
            "quality_reasons": manifest["quality_reasons"],
            "manifest_path": f"datasets/quarantine/{manifest['dataset_id']}.manifest.json",
        })
    (catalog / "DATA_INDEX.json").write_text(json.dumps({"shards": rows}), encoding="utf-8")
    (catalog / "DATA_METRICS.json").write_text(
        json.dumps({"totals": {"TOTAL_QUARANTINED_RECORDS": 20}}),
        encoding="utf-8",
    )

    report = build(tmp_path)

    assert report["quarantined_record_count"] == 20
    assert report["quarantine_total_matches_metrics"] is True
    assert report["historical_live_only_false_reject_count"] == 1
    assert report["potential_false_non_safe_count"] == 1
    assert report["by_category"]["HISTORICAL_LIVE_RULE_FALSE_QUARANTINE"]["shards"] == 1
    assert report["by_category"]["PARTIAL_EVIDENCE"]["shards"] == 1
