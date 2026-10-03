from __future__ import annotations

import json

from hl_observer.collection.partitioned_tick_dataset import PartitionedTickDatasetWriter
from hl_observer.collection.tick_dataset import TickEnvelope
from hl_observer.datasets.v2_export import build_manifest_from_tick_shard


def envelope(source: str, channel: str, instrument: str, ts: int) -> TickEnvelope:
    return TickEnvelope(
        source_id=source,
        channel=channel,
        instrument=instrument,
        event_kind="UPDATE",
        raw_payload={"ts": ts, "instrument": instrument},
        exchange_ts_ms=ts,
        received_ts_ms=ts + 5,
        local_monotonic_ns=ts * 1_000,
        connection_id="c1",
        sequence=ts,
        provenance={
            "access": "read_only",
            "authenticated": False,
        },
    )


def test_partitioned_writer_never_mixes_symbol_or_channel(tmp_path) -> None:
    writer = PartitionedTickDatasetWriter(tmp_path, rotate_bytes=10_000_000)
    batch = [
        envelope("bybit_public_ws", "l2Book", "BTCUSDT", 1000),
        envelope("bybit_public_ws", "trades", "BTCUSDT", 1001),
        envelope("bybit_public_ws", "l2Book", "ETHUSDT", 1002),
    ]
    records = writer.append_batch_records(batch)
    assert len(records) == 3
    assert writer.stats()["partition_count"] == 3

    paths = sorted(tmp_path.glob("*/*/*/ticks.current.jsonl"))
    assert len(paths) == 3
    for path in paths:
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        assert len({(row["source_id"], row["channel"], row["instrument"]) for row in rows}) == 1


def test_rotate_all_seals_each_partition(tmp_path) -> None:
    writer = PartitionedTickDatasetWriter(tmp_path, rotate_bytes=10_000_000)
    writer.append(envelope("okx_public_ws", "l2Book", "BTC-USDT-SWAP", 1000))
    writer.append(envelope("okx_public_ws", "trades", "BTC-USDT-SWAP", 1001))
    shards = writer.rotate_all()
    assert len(shards) == 2
    assert all(path.name.endswith(".jsonl.gz") for path in shards)


def test_unicode_instruments_cannot_collapse_into_one_partition(tmp_path) -> None:
    writer = PartitionedTickDatasetWriter(tmp_path, rotate_bytes=10_000_000)
    instruments = ("哈基米USDT", "牛来USDT", "龙虾USDT")
    writer.append_batch_records(
        [
            envelope("bitget_public_rest", "instrument_metadata", symbol, 2000 + index)
            for index, symbol in enumerate(instruments)
        ]
    )

    shards = writer.rotate_all()
    assert len(shards) == 3

    manifests = [
        build_manifest_from_tick_shard(
            shard,
            collector_version="test-unicode-partitions",
        )
        for shard in shards
    ]
    assert {manifest["symbol"] for manifest in manifests} == set(instruments)
    assert all(manifest["source"] == "bitget_public_rest" for manifest in manifests)
    assert all(manifest["family"] == "instrument_metadata" for manifest in manifests)

