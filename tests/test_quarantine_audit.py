from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from tools.build_quarantine_audit import build
from tools.repair_stale_safe_classifications import repair


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
        "release": {
            "repository": "Rapt0r06300/hyperliquid-smart-wallet-observer",
            "tag": "archive-v2-test",
            "asset_name": dataset_id + ".jsonl.gz",
            "remote_size": 100,
            "remote_digest": "sha256:" + "a" * 64,
        },
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
    source_sha = hashlib.sha256((catalog / "DATA_INDEX.json").read_bytes()).hexdigest()
    (catalog / "DATA_METRICS.json").write_text(
        json.dumps({
            "schema_version": "alina.data_metrics.v4",
            "source_index_sha256": source_sha,
            "totals": {
                "TOTAL_SHARDS": 2, "SAFE_SHARDS": 0,
                "PARTIAL_SHARDS": 2, "REJECTED_SHARDS": 0,
                "TOTAL_QUARANTINED_RECORDS": 20, "TOTAL_REJECTED_RECORDS": 0,
            },
        }), encoding="utf-8",
    )

    report = build(tmp_path)

    assert report["quarantined_record_count"] == 20
    assert report["quarantine_total_matches_metrics"] is True
    assert report["historical_live_only_false_reject_count"] == 1
    assert report["potential_false_non_safe_count"] == 1
    assert report["by_category"]["HISTORICAL_LIVE_RULE_FALSE_QUARANTINE"]["shards"] == 1
    assert report["by_category"]["PARTIAL_EVIDENCE"]["shards"] == 1


def test_repair_stale_safe_classification_preserves_evidence(tmp_path: Path):
    catalog = tmp_path / "catalog"
    quarantine = tmp_path / "datasets" / "quarantine"
    catalog.mkdir()
    quarantine.mkdir(parents=True)

    manifest = _manifest("stale-safe", safe_now=True)
    manifest_path = quarantine / "stale-safe.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    row = {
        "dataset_id": "stale-safe",
        "venue": "bybit",
        "family": "trades",
        "symbol": "BTCUSDT",
        "quality_status": "PARTIAL",
        "quality_reasons": ["UNIQUE_TRADE_COUNT_NOT_EXACT"],
        "record_count": 10,
        "event_count": 10,
        "replay_compatible": True,
        "replay_schema_version": "alina.replay.v2",
        "replay_reason": "STRICT_PARSE_CHRONOLOGY_OK",
        "trade_count": 10,
        "trade_count_exact": True,
        "unique_trade_count": 10,
        "unique_trade_count_exact": True,
        "custom_evidence": "keep-me",
        "manifest_path": "datasets/quarantine/stale-safe.manifest.json",
    }
    (catalog / "DATA_INDEX.json").write_text(
        json.dumps({"active_data_status": "PARTIAL", "shards": [row]}),
        encoding="utf-8",
    )
    (catalog / "DATA_QUALITY_REGISTRY.json").write_text(
        json.dumps({"active_dataset": {}}),
        encoding="utf-8",
    )
    (catalog / "DATA_CATALOG.json").write_text(
        json.dumps({"active_data_status": "PARTIAL"}),
        encoding="utf-8",
    )

    result = repair(tmp_path)

    assert result["repaired_count"] == 1
    assert result["repaired_record_count"] == 10
    safe_path = tmp_path / "datasets" / "safe" / "stale-safe.manifest.json"
    assert safe_path.is_file()
    assert not manifest_path.exists()
    repaired_manifest = json.loads(safe_path.read_text(encoding="utf-8"))
    assert repaired_manifest["quality_status"] == "SAFE"
    assert repaired_manifest["quality_reasons"] == []
    assert repaired_manifest["validation_allowed"] is True

    index = json.loads((catalog / "DATA_INDEX.json").read_text(encoding="utf-8"))
    repaired_row = index["shards"][0]
    assert repaired_row["quality_status"] == "SAFE"
    assert repaired_row["manifest_path"] == "datasets/safe/stale-safe.manifest.json"
    assert repaired_row["replay_compatible"] is True
    assert repaired_row["trade_count_exact"] is True
    assert repaired_row["unique_trade_count_exact"] is True
    assert repaired_row["custom_evidence"] == "keep-me"

    registry = json.loads((catalog / "DATA_QUALITY_REGISTRY.json").read_text(encoding="utf-8"))
    data_catalog = json.loads((catalog / "DATA_CATALOG.json").read_text(encoding="utf-8"))
    assert registry["active_dataset"]["safe_count"] == 1
    assert registry["active_dataset"]["partial_count"] == 0
    assert data_catalog["safe_shard_count"] == 1
    assert data_catalog["partial_shard_count"] == 0



def test_compact_root_causes_keeps_reasons_and_never_promotes():
    from tools.build_quarantine_audit import compact_root_causes

    audit = {
        "receipt_digest": "sha",
        "source_index_sha256": "sha-index",
        "source_shard_count": 4,
        "non_safe_shard_count": 2,
        "by_status": {"REJECT": {"shards": 1, "records": 2}},
        "by_venue": {},
        "by_family": {},
        "by_category": {},
        "current_reason_counts": {"DESYNC": {"shards": 1, "records": 2}},
        "stored_reason_counts": {},
        "non_safe_shards": [
            {"venue": "binance", "family": "l2book", "record_count": 2,
             "current_reasons": ["DESYNC", "SEQUENCE_OR_QUEUE_GAP"]},
            {"venue": "bybit", "family": "ticker", "record_count": 10,
             "current_reasons": ["RECONCILIATION_UNVERIFIED"]},
        ],
    }
    compact = compact_root_causes(audit)
    assert compact["non_safe_shards"] == 2
    assert compact["by_venue_family"]["binance|l2book"]["shards"] == 1
    assert compact["reason_by_venue_family"]["binance|l2book|DESYNC"]["records"] == 2
    assert compact["status"] == "DIAGNOSIS_ONLY"
    assert compact["validation_allowed"] is False
    assert "non_safe_shards" not in compact["by_status"]



def test_stale_repair_wont_mark_missing_release_coordinates_safe(tmp_path: Path):
    catalog = tmp_path / "catalog"
    q = tmp_path / "datasets" / "quarantine"
    catalog.mkdir()
    q.mkdir(parents=True)
    doc = _manifest("missing-release", safe_now=True)
    doc.pop("release", None)
    (q / "missing-release.manifest.json").write_text(json.dumps(doc))
    (catalog / "DATA_INDEX.json").write_text(json.dumps({"shards": [{
        "dataset_id": "missing-release",
        "manifest_path": "datasets/quarantine/missing-release.manifest.json",
        "quality_status": "PARTIAL",
    }]}))
    (catalog / "DATA_QUALITY_REGISTRY.json").write_text(json.dumps({}))
    (catalog / "DATA_CATALOG.json").write_text(json.dumps({}))
    result = repair(tmp_path)
    assert result["repaired_count"] == 0
    assert not (tmp_path / "datasets" / "safe" / "missing-release.manifest.json").exists()



def test_quarantine_cause_census_separates_real_drop_from_legacy_repeated_loss():
    from tools.build_quarantine_audit import compact_root_causes
    rows = [
        {
            "venue": "gate", "family": "l2Book", "record_count": 10,
            "collection_queue_drops": 6, "integrity_gap_count": 7,
            "queue_drop_attribution_method": None,
            "current_reasons": ["FATAL_INTEGRITY:gap_count=7"],
        },
        {
            "venue": "bitget", "family": "bbo", "record_count": 20,
            "collection_queue_drops": 2, "integrity_gap_count": 2,
            "queue_drop_attribution_method": "connection_receive_second_v1",
        },
        {
            "venue": "okx", "family": "l2Book", "record_count": 30,
            "collection_queue_drops": 0, "integrity_gap_count": 3,
        },
    ]
    doc = compact_root_causes({"non_safe_shards": rows})
    causes = doc["source_gap_causes"]
    assert causes["gate|l2Book|LEGACY_CUMULATIVE_INGRESS_LOSS"]["shards"] == 1
    assert causes["bitget|bbo|ATTRIBUTED_INGRESS_LOSS_V1"]["shards"] == 1
    assert causes["okx|l2Book|SOURCE_SEQUENCE_OR_OTHER_GAP_NO_QUEUE_LOSS"]["shards"] == 1
    assert doc["queue_drops_sum_across_non_safe_manifests"] == 8
    assert doc["queue_drop_sum_is_not_distinct_frames"] is True
    assert doc["validation_allowed"] is False


def test_quarantine_audit_rejects_stale_sha_and_duplicate_ids(tmp_path: Path):
    (tmp_path / "catalog").mkdir()
    index_path = tmp_path / "catalog" / "DATA_INDEX.json"
    metrics_path = tmp_path / "catalog" / "DATA_METRICS.json"
    row = {"dataset_id": "one", "quality_status": "PARTIAL", "record_count": 1}
    index_path.write_text(json.dumps({"shards": [row]}), encoding="utf-8")
    metrics = {
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": "0" * 64,
        "totals": {"TOTAL_SHARDS": 1, "SAFE_SHARDS": 0,
                   "PARTIAL_SHARDS": 1, "REJECTED_SHARDS": 0,
                   "TOTAL_QUARANTINED_RECORDS": 1, "TOTAL_REJECTED_RECORDS": 0},
    }
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    with pytest.raises(ValueError, match="QUARANTINE_STALE_METRICS"):
        build(tmp_path)

    metrics["source_index_sha256"] = hashlib.sha256(index_path.read_bytes()).hexdigest()
    metrics["totals"]["TOTAL_QUARANTINED_RECORDS"] = 2
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
    with pytest.raises(ValueError, match="QUARANTINE_COUNT_MISMATCH"):
        build(tmp_path)  # A metric total is no substitute for indexed record evidence.


def test_quarantine_audit_rejects_duplicate_shard_id_even_with_matched_metrics(tmp_path: Path):
    (tmp_path / "catalog").mkdir()
    path = tmp_path / "catalog" / "DATA_INDEX.json"
    rows = [
        {"dataset_id": "same", "quality_status": "PARTIAL", "record_count": 1},
        {"dataset_id": "same", "quality_status": "REJECT", "record_count": 2},
    ]
    path.write_text(json.dumps({"shards": rows}), encoding="utf-8")
    (tmp_path / "catalog" / "DATA_METRICS.json").write_text(json.dumps({
        "schema_version": "alina.data_metrics.v4",
        "source_index_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "totals": {"TOTAL_SHARDS": 2, "SAFE_SHARDS": 0,
                   "PARTIAL_SHARDS": 1, "REJECTED_SHARDS": 1,
                   "TOTAL_QUARANTINED_RECORDS": 1, "TOTAL_REJECTED_RECORDS": 2},
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="QUARANTINE_DUPLICATE_IDENTITY"):
        build(tmp_path)
