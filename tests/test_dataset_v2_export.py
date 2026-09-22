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


def test_okx_prev_sequence_gap_is_counted_in_manifest(tmp_path) -> None:
    writer = PartitionedTickDatasetWriter(tmp_path)
    writer.append(
        TickEnvelope(
            source_id="okx_public_ws",
            channel="l2Book",
            instrument="BTC-USDT-SWAP",
            event_kind="UPDATE",
            raw_payload={"arg": {"channel": "books"}},
            exchange_ts_ms=1000,
            received_ts_ms=1005,
            local_monotonic_ns=100,
            connection_id="okx-1",
            sequence=10,
            provenance={"access": "read_only", "authenticated": False},
            parsed_summary={"prev_sequence": -1},
        )
    )
    writer.append(
        TickEnvelope(
            source_id="okx_public_ws",
            channel="l2Book",
            instrument="BTC-USDT-SWAP",
            event_kind="UPDATE",
            raw_payload={"arg": {"channel": "books"}},
            exchange_ts_ms=1010,
            received_ts_ms=1015,
            local_monotonic_ns=200,
            connection_id="okx-1",
            sequence=12,
            provenance={"access": "read_only", "authenticated": False},
            parsed_summary={"prev_sequence": 8},
        )
    )
    [shard] = writer.rotate_all()
    manifest = build_manifest_from_tick_shard(shard, collector_version="abc123")
    assert manifest["integrity"]["gap_count"] == 1


def test_binance_previous_update_gap_is_counted_in_manifest(tmp_path) -> None:
    writer = PartitionedTickDatasetWriter(tmp_path)
    writer.append(
        TickEnvelope(
            source_id="binance_usdm_public",
            channel="l2Book",
            instrument="BTCUSDT",
            event_kind="INCREMENTAL",
            raw_payload={"e": "depthUpdate"},
            exchange_ts_ms=1000,
            received_ts_ms=1005,
            local_monotonic_ns=100,
            connection_id="bin-1",
            sequence=100,
            provenance={"access": "read_only", "authenticated": False},
            parsed_summary={
                "first_update_id": 99,
                "previous_update_id": 98,
            },
        )
    )
    writer.append(
        TickEnvelope(
            source_id="binance_usdm_public",
            channel="l2Book",
            instrument="BTCUSDT",
            event_kind="INCREMENTAL",
            raw_payload={"e": "depthUpdate"},
            exchange_ts_ms=1010,
            received_ts_ms=1015,
            local_monotonic_ns=200,
            connection_id="bin-1",
            sequence=105,
            provenance={"access": "read_only", "authenticated": False},
            parsed_summary={
                "first_update_id": 104,
                "previous_update_id": 99,
            },
        )
    )
    [shard] = writer.rotate_all()
    manifest = build_manifest_from_tick_shard(shard, collector_version="abc123")
    assert manifest["integrity"]["gap_count"] >= 1


def test_binance_futures_predecessor_id_is_authoritative_for_continuity(tmp_path) -> None:
    writer = PartitionedTickDatasetWriter(tmp_path)
    for exchange_ts, sequence, previous, first in (
        (1000, 105, 100, 103),
        (1010, 110, 105, 108),
        (1020, 115, 110, 113),
    ):
        writer.append(
            TickEnvelope(
                source_id="binance_usdm_public",
                channel="l2Book",
                instrument="BTCUSDT",
                event_kind="INCREMENTAL",
                raw_payload={"e": "depthUpdate"},
                exchange_ts_ms=exchange_ts,
                received_ts_ms=exchange_ts + 5,
                local_monotonic_ns=exchange_ts * 1000,
                connection_id="bin-1",
                sequence=sequence,
                gap_count=0,
                provenance={
                    "access": "read_only",
                    "authenticated": False,
                    "transport": "websocket",
                    "gap_count_semantics": "event_delta",
                },
                parsed_summary={
                    "first_update_id": first,
                    "previous_update_id": previous,
                    "book_state": "EXPLOITABLE",
                },
            )
        )
    [shard] = writer.rotate_all()
    manifest = build_manifest_from_tick_shard(shard, collector_version="abc123")
    assert manifest["integrity"]["gap_count"] == 0
    assert manifest["integrity"]["desync_count"] == 0


def test_binance_bootstrap_state_is_not_desync_but_real_gap_is_counted(tmp_path) -> None:
    writer = PartitionedTickDatasetWriter(tmp_path)
    writer.append(
        TickEnvelope(
            source_id="binance_usdm_public",
            channel="l2Book",
            instrument="ETHUSDT",
            event_kind="INCREMENTAL",
            raw_payload={"e": "depthUpdate"},
            exchange_ts_ms=1000,
            received_ts_ms=1005,
            local_monotonic_ns=100,
            connection_id="bin-1",
            sequence=100,
            gap_count=0,
            provenance={
                "access": "read_only",
                "authenticated": False,
                "transport": "websocket",
                "gap_count_semantics": "event_delta",
            },
            parsed_summary={
                "previous_update_id": 99,
                "book_state": "BUFFERING_SNAPSHOT",
            },
        )
    )
    writer.append(
        TickEnvelope(
            source_id="binance_usdm_public",
            channel="l2Book",
            instrument="ETHUSDT",
            event_kind="INCREMENTAL",
            raw_payload={"e": "depthUpdate"},
            exchange_ts_ms=1010,
            received_ts_ms=1015,
            local_monotonic_ns=200,
            connection_id="bin-1",
            sequence=105,
            gap_count=1,
            provenance={
                "access": "read_only",
                "authenticated": False,
                "transport": "websocket",
                "gap_count_semantics": "event_delta",
            },
            parsed_summary={
                "previous_update_id": 100,
                "book_state": "DESYNC",
            },
        )
    )
    [shard] = writer.rotate_all()
    manifest = build_manifest_from_tick_shard(shard, collector_version="abc123")
    assert manifest["integrity"]["gap_count"] >= 1
    assert manifest["integrity"]["desync_count"] == 1


def test_receive_only_repeated_observations_are_not_duplicates(tmp_path) -> None:
    writer = PartitionedTickDatasetWriter(tmp_path)
    for received, mono in ((1000, 100), (1010, 200)):
        writer.append(
            TickEnvelope(
                source_id="hyperliquid_public_ws",
                channel="activeAssetCtx",
                instrument="BTC",
                event_kind="SNAPSHOT",
                raw_payload={
                    "channel": "activeAssetCtx",
                    "data": {"coin": "BTC", "ctx": {"markPx": "100"}},
                },
                exchange_ts_ms=None,
                received_ts_ms=received,
                local_monotonic_ns=mono,
                connection_id="hl-1",
                sequence=None,
                provenance={
                    "access": "read_only",
                    "authenticated": False,
                    "transport": "websocket",
                    "timestamp_semantics": "receive_observation_time_only",
                },
            )
        )
    [shard] = writer.rotate_all()
    manifest = build_manifest_from_tick_shard(shard, collector_version="abc123")
    assert manifest["integrity"]["duplicate_count"] == 0
    assert manifest["integrity"]["duplicates_deduped"] is True
