from __future__ import annotations

import hashlib

from hl_observer.collection.partitioned_tick_dataset import PartitionedTickDatasetWriter
from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.datasets.v2_pipeline import (
    assess_manifest,
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
