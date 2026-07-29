from __future__ import annotations

import hashlib

from hl_observer.collection.tick_dataset import (
    SCHEMA_VERSION,
    TickDatasetWriter,
    TickEnvelope,
)
from hl_observer.realtime.feed_quality import FeedEventKind


def test_tick_dataset_preserves_raw_payload_three_clocks_and_provenance(tmp_path) -> None:
    writer = TickDatasetWriter(tmp_path / "ticks", rotate_bytes=1_000_000)
    raw = '{"channel":"bbo","data":{"coin":"BTC"}}'
    writer.append(
        TickEnvelope(
            source_id="hyperliquid_mainnet_readonly",
            channel="bbo",
            instrument="BTC",
            event_kind=FeedEventKind.SNAPSHOT,
            raw_payload=raw,
            exchange_ts_ms=1_000,
            received_ts_ms=1_012,
            written_ts_ms=1_020,
            local_monotonic_ns=123_456,
            connection_id="hl-1",
            sequence=7,
            reconnect_count=2,
            gap_count=1,
            provenance={
                "url": "wss://api.hyperliquid.xyz/ws",
                "network": "mainnet",
                "access": "read_only",
            },
            parsed_summary={"best_bid": 100, "best_ask": 101},
        )
    )
    [record] = list(writer.iter_records())
    assert record["schema_version"] == SCHEMA_VERSION
    assert record["raw_payload"] == raw
    assert record["raw_sha256"] == hashlib.sha256(raw.encode()).hexdigest()
    assert record["exchange_ts_ms"] == 1_000
    assert record["received_ts_ms"] == 1_012
    assert record["written_ts_ms"] == 1_020
    assert record["local_monotonic_ns"] == 123_456
    assert record["recv_wall_ts_ms"] == 1_012
    assert record["write_wall_ts_ms"] == 1_020
    assert record["recv_mono_ns"] == 123_456
    assert record["event_kind"] == "SNAPSHOT"
    assert record["provenance"]["access"] == "read_only"
    assert record["real_execution"] is False


def test_tick_dataset_rotation_is_replayable_and_keeps_all_records(tmp_path) -> None:
    writer = TickDatasetWriter(tmp_path / "ticks", rotate_bytes=1)
    for index in range(3):
        writer.append(
            TickEnvelope(
                source_id="hyperliquid_mainnet_readonly",
                channel="trades",
                instrument="ETH",
                event_kind=FeedEventKind.EVENT,
                raw_payload={"tid": index, "px": str(100 + index)},
                exchange_ts_ms=1_000 + index,
                received_ts_ms=1_010 + index,
            )
        )

    records = list(writer.iter_records())
    assert [record["parsed_summary"] for record in records] == [{}, {}, {}]
    assert [record["exchange_ts_ms"] for record in records] == [1_000, 1_001, 1_002]
    assert len(list((tmp_path / "ticks" / "shards").glob("*.jsonl.gz"))) == 3
    assert writer.manifest_path.exists()
