from __future__ import annotations

import hashlib

from hl_observer.collection.partitioned_tick_dataset import PartitionedTickDatasetWriter
from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.datasets.v2_export import build_manifest_from_tick_shard


def _event(ts: int) -> TickEnvelope:
    return TickEnvelope(
        source_id="bybit_public_ws",
        channel="l2Book",
        instrument="BTCUSDT",
        event_kind="UPDATE",
        raw_payload={"topic": "orderbook.200.BTCUSDT", "ts": ts},
        exchange_ts_ms=ts,
        received_ts_ms=ts + 5,
        local_monotonic_ns=ts * 1_000,
        connection_id="bybit-1",
        sequence=ts,
        provenance={
            "access": "read_only",
            "authenticated": False,
        },
    )


def test_manifest_is_derived_from_real_partitioned_shard(tmp_path) -> None:
    writer = PartitionedTickDatasetWriter(tmp_path)
    writer.append(_event(1000))
    writer.append(_event(1010))
    [shard] = writer.rotate_all()

    manifest = build_manifest_from_tick_shard(
        shard,
        collector_version="abc123",
        reconciliation_status="UNVERIFIED",
        required_channels=["l2Book"],
    )
    assert manifest["venue"] == "bybit"
    assert manifest["family"] == "l2Book"
    assert manifest["symbol"] == "BTCUSDT"
    assert manifest["event_count"] == 2
    assert manifest["start_ts_ms"] == 1005
    assert manifest["end_ts_ms"] == 1015
    assert manifest["bytes"] == shard.stat().st_size
    assert manifest["sha256"] == hashlib.sha256(shard.read_bytes()).hexdigest()
    assert manifest["asset_verified"] is False
    assert manifest["reconciliation"]["status"] == "UNVERIFIED"
    assert manifest["validation_allowed"] is False
    assert manifest["integrity"]["missing_monotonic_count"] == 0


def test_mixed_shard_is_refused(tmp_path) -> None:
    from hl_observer.collection.tick_dataset import TickDatasetWriter

    writer = TickDatasetWriter(tmp_path / "mixed", rotate_bytes=10_000_000)
    writer.append(_event(1000))
    other = _event(1010)
    other.instrument = "ETHUSDT"
    writer.append(other)
    shard = writer.rotate()
    assert shard is not None

    try:
        build_manifest_from_tick_shard(shard, collector_version="abc123")
    except ValueError as exc:
        assert "one source/channel/instrument" in str(exc)
    else:
        raise AssertionError("mixed shard must be refused")


def test_missing_authenticated_provenance_is_not_silently_treated_as_false(tmp_path) -> None:
    from hl_observer.collection.partitioned_tick_dataset import PartitionedTickDatasetWriter
    from hl_observer.collection.tick_dataset import TickEnvelope

    writer = PartitionedTickDatasetWriter(tmp_path)
    writer.append(
        TickEnvelope(
            source_id="hyperliquid_public_ws",
            channel="bbo",
            instrument="BTC",
            event_kind="UPDATE",
            raw_payload={"channel": "bbo"},
            exchange_ts_ms=1000,
            received_ts_ms=1005,
            local_monotonic_ns=123,
            provenance={"access": "read_only"},
        )
    )
    [shard] = writer.rotate_all()
    manifest = build_manifest_from_tick_shard(shard, collector_version="abc123")
    assert manifest["provenance"]["authenticated"] is None
