from __future__ import annotations

import hashlib

from hl_observer.collection.partitioned_tick_dataset import PartitionedTickDatasetWriter
from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.datasets.v2_pipeline import (
    assess_manifest,
    attach_reconciliation,
    build_bundle,
    verify_remote_asset,
)


def _event(ts: int, *, connection: str = "ws-1", gap_count: int = 0) -> TickEnvelope:
    return TickEnvelope(
        source_id="bybit_public_ws",
        channel="l2Book",
        instrument="BTCUSDT",
        event_kind="UPDATE",
        raw_payload={"topic": "orderbook.200.BTCUSDT", "ts": ts},
        exchange_ts_ms=ts,
        received_ts_ms=ts + 5,
        local_monotonic_ns=ts * 1_000,
        connection_id=connection,
        sequence=ts,
        gap_count=gap_count,
        provenance={
            "access": "read_only",
            "transport": "websocket",
            "authenticated": False,
        },
        parsed_summary={
            "transport_rtt_ms": 12.0,
            "clock_offset_ms": 2.0,
        },
    )


def test_connection_change_seals_previous_partition_epoch(tmp_path) -> None:
    writer = PartitionedTickDatasetWriter(tmp_path / "ticks", rotate_bytes=10_000_000)
    writer.append_batch_records(
        [
            _event(1000, connection="ws-a"),
            _event(1010, connection="ws-a"),
            _event(1020, connection="ws-b"),
        ]
    )
    writer.rotate_all()
    shards = sorted((tmp_path / "ticks").glob("**/shards/*.jsonl.gz"))
    assert len(shards) == 2


def test_remote_digest_is_required_before_safe(tmp_path) -> None:
    writer = PartitionedTickDatasetWriter(tmp_path / "ticks", rotate_bytes=10_000_000)
    writer.append(_event(1000))
    writer.append(_event(1010))
    writer.rotate_all()

    index = build_bundle(
        tmp_path / "ticks",
        tmp_path / "bundle",
        collector_version="a" * 40,
    )
    assert index["shard_count"] == 1
    manifest_path = next((tmp_path / "bundle" / "manifests").glob("*.json"))
    import json
    manifest = json.loads(manifest_path.read_text())
    assert manifest["quality_status"] == "PARTIAL"
    assert manifest["reconciliation"]["status"] == "SOURCE_CONTINUITY_VERIFIED"
    assert "REMOTE_ASSET_NOT_VERIFIED" in manifest["quality_reasons"]

    asset = tmp_path / "bundle" / "assets" / manifest["release_asset"]
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    verified = verify_remote_asset(
        manifest,
        repository="Rapt0r06300/alina-smartflow-datasets-v2",
        release_tag="data-v2-run-1-1",
        release_id=10,
        asset_id=20,
        asset_name=manifest["release_asset"],
        remote_size=asset.stat().st_size,
        remote_digest="sha256:" + digest,
    )
    assert verified["quality_status"] == "SAFE"
    assert verified["validation_allowed"] is True
    assert verified["proof_of_pnl_allowed"] is True


def test_gap_inside_shard_is_rejected_even_with_remote_hash(tmp_path) -> None:
    writer = PartitionedTickDatasetWriter(tmp_path / "ticks", rotate_bytes=10_000_000)
    writer.append(_event(1000, gap_count=0))
    writer.append(_event(1010, gap_count=1))
    writer.rotate_all()
    build_bundle(
        tmp_path / "ticks",
        tmp_path / "bundle",
        collector_version="b" * 40,
    )
    import json
    manifest_path = next((tmp_path / "bundle" / "manifests").glob("*.json"))
    manifest = json.loads(manifest_path.read_text())
    asset = tmp_path / "bundle" / "assets" / manifest["release_asset"]
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    verified = verify_remote_asset(
        manifest,
        repository="Rapt0r06300/alina-smartflow-datasets-v2",
        release_tag="data-v2-run-2-1",
        release_id=11,
        asset_id=21,
        asset_name=manifest["release_asset"],
        remote_size=asset.stat().st_size,
        remote_digest="sha256:" + digest,
    )
    status, reasons = assess_manifest(verified)
    assert status == "REJECT"
    assert "SEQUENCE_OR_QUEUE_GAP" in reasons


def test_wrong_remote_digest_never_promotes_safe(tmp_path) -> None:
    writer = PartitionedTickDatasetWriter(tmp_path / "ticks", rotate_bytes=10_000_000)
    writer.append(_event(1000))
    writer.rotate_all()
    build_bundle(
        tmp_path / "ticks",
        tmp_path / "bundle",
        collector_version="c" * 40,
    )
    import json
    manifest = json.loads(next((tmp_path / "bundle" / "manifests").glob("*.json")).read_text())
    asset = tmp_path / "bundle" / "assets" / manifest["release_asset"]
    verified = verify_remote_asset(
        manifest,
        repository="Rapt0r06300/alina-smartflow-datasets-v2",
        release_tag="data-v2-run-3-1",
        release_id=12,
        asset_id=22,
        asset_name=manifest["release_asset"],
        remote_size=asset.stat().st_size,
        remote_digest="sha256:" + "0" * 64,
    )
    assert verified["asset_verified"] is False
    assert verified["quality_status"] == "PARTIAL"
    assert verified["validation_allowed"] is False


def test_collection_queue_drop_rejects_every_native_bundle_shard(tmp_path) -> None:
    writer = PartitionedTickDatasetWriter(tmp_path / "ticks", rotate_bytes=10_000_000)
    writer.append(_event(1000))
    writer.append(_event(1010))
    writer.rotate_all()

    index = build_bundle(
        tmp_path / "ticks",
        tmp_path / "bundle",
        collector_version="d" * 40,
        collection_queue_drops=3,
    )
    assert index["collection_queue_drops"] == 3
    assert index["reject_count"] == index["shard_count"] == 1
    assert index["safe_count"] == 0

    import json
    manifest = json.loads(
        next((tmp_path / "bundle" / "manifests").glob("*.json")).read_text()
    )
    assert manifest["collection_queue_drops"] == 3
    assert manifest["integrity"]["gap_count"] >= 3
    assert manifest["quality_status"] == "REJECT"
    assert "SEQUENCE_OR_QUEUE_GAP" in manifest["quality_reasons"]


def test_trade_shard_requires_explicit_matched_reconciliation(tmp_path) -> None:
    writer = PartitionedTickDatasetWriter(tmp_path / "ticks", rotate_bytes=10_000_000)
    trade = TickEnvelope(
        source_id="bybit_public_ws",
        channel="trades",
        instrument="BTCUSDT",
        event_kind="EVENT",
        raw_payload={"topic": "publicTrade.BTCUSDT", "ts": 1000, "data": [{"i": "a"}]},
        exchange_ts_ms=1000,
        received_ts_ms=1005,
        local_monotonic_ns=1_000_000,
        connection_id="ws-1",
        sequence=1,
        provenance={
            "access": "read_only",
            "transport": "websocket",
            "authenticated": False,
        },
    )
    writer.append(trade)
    writer.rotate_all()

    build_bundle(
        tmp_path / "ticks",
        tmp_path / "bundle",
        collector_version="e" * 40,
    )
    import json
    manifest_path = next((tmp_path / "bundle" / "manifests").glob("*.json"))
    manifest = json.loads(manifest_path.read_text())
    assert manifest["family"] == "trades"
    assert manifest["reconciliation"]["status"] == "UNVERIFIED"
    assert manifest["quality_status"] == "PARTIAL"
    assert "RECONCILIATION_MATCH_REQUIRED" in manifest["quality_reasons"]

    asset = tmp_path / "bundle" / "assets" / manifest["release_asset"]
    digest = hashlib.sha256(asset.read_bytes()).hexdigest()
    verified = verify_remote_asset(
        manifest,
        repository="Rapt0r06300/alina-smartflow-datasets-v2",
        release_tag="data-v2-run-trades",
        release_id=30,
        asset_id=40,
        asset_name=manifest["release_asset"],
        remote_size=asset.stat().st_size,
        remote_digest="sha256:" + digest,
    )
    assert verified["quality_status"] == "PARTIAL"

    reconciled = attach_reconciliation(
        verified,
        {
            "status": "MATCHED",
            "live_count": 1,
            "reference_count": 1,
            "matched_count": 1,
            "missing_from_live": 0,
            "live_only": 0,
            "duplicate_live_keys": 0,
            "backfill_status": "OK",
        },
    )
    assert reconciled["quality_status"] == "SAFE"
    assert reconciled["validation_allowed"] is True


def test_partial_trade_reconciliation_never_promotes_safe(tmp_path) -> None:
    manifest = {
        "event_count": 1,
        "bytes": 10,
        "start_ts_ms": 1000,
        "end_ts_ms": 1000,
        "sha256": "f" * 64,
        "collector_version": "f" * 40,
        "family": "trades",
        "asset_verified": True,
        "integrity": {
            "gap_count": 0,
            "duplicate_count": 0,
            "regression_count": 0,
            "missing_timestamp_count": 0,
            "missing_monotonic_count": 0,
            "desync_count": 0,
        },
        "provenance": {
            "public_data_only": True,
            "authenticated": False,
            "real_execution": False,
            "transports": ["websocket"],
        },
        "synchronization": {"connection_count": 1},
        "required_channels": [],
        "observed_channels": ["trades"],
        "cost_model": {"applicable": False, "ready": False},
        "reconciliation": {"status": "UNVERIFIED"},
    }
    partial = attach_reconciliation(
        manifest,
        {
            "status": "PARTIAL",
            "live_count": 10,
            "reference_count": 11,
            "matched_count": 10,
            "missing_from_live": 1,
            "live_only": 0,
            "duplicate_live_keys": 0,
            "backfill_status": "OK",
        },
    )
    assert partial["quality_status"] == "PARTIAL"
    assert "RECONCILIATION_MATCH_REQUIRED" in partial["quality_reasons"]
