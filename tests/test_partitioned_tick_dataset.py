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




def test_rotate_all_includes_previous_size_rotations_without_data_loss(tmp_path) -> None:
    import gzip
    writer = PartitionedTickDatasetWriter(tmp_path, rotate_bytes=1)
    rows = [envelope("bybit_public_ws", "trades", "BTCUSDT", 1000 + i) for i in range(5)]
    assert len(writer.append_batch_records(rows)) == 5
    # Every append may have auto-rotated; rotate_all must return ALL old assets.
    files = writer.rotate_all()
    assert files
    restored = []
    for path in files:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            restored += [json.loads(line) for line in handle]
    assert len(restored) == 5
    assert sorted(row["exchange_ts_ms"] for row in restored) == [1000, 1001, 1002, 1003, 1004]
    assert all(path.with_name(path.name + ".manifest.json").exists() for path in files)


def test_rotate_all_includes_reconnect_shards_and_preserves_single_connection(tmp_path) -> None:
    import gzip
    writer = PartitionedTickDatasetWriter(tmp_path, rotate_bytes=10_000_000)
    event1 = envelope("bybit_public_ws", "l2Book", "BTCUSDT", 1000)
    event2 = envelope("bybit_public_ws", "l2Book", "BTCUSDT", 1001)
    event3 = envelope("bybit_public_ws", "l2Book", "BTCUSDT", 1002)
    event1.connection_id = "conn-a"
    event2.connection_id = "conn-b"
    event3.connection_id = "conn-c"
    # append() previously bypassed epoch rotation altogether.
    assert writer.append(event1) == 1
    assert writer.append(event2) == 1
    assert writer.append(event3) == 1
    files = writer.rotate_all()
    assert len(files) == 3
    identities = []
    for path in files:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            rows = [json.loads(line) for line in handle]
        assert len(rows) == 1
        identities.append(rows[0]["connection_id"])
    assert set(identities) == {"conn-a", "conn-b", "conn-c"}
    assert len(writer.rotate_all()) == 3


def test_mix_auto_rotate_and_batch_reconnect_preserves_every_record(tmp_path):
    import gzip
    writer = PartitionedTickDatasetWriter(tmp_path, rotate_bytes=750)
    events = [envelope("gate_public_ws", "trades", "ETH_USDT", 1000+i) for i in range(11)]
    for i, event in enumerate(events):
        event.connection_id = "first" if i < 5 else "second"
    assert len(writer.append_batch_records(events)) == len(events)
    files = writer.rotate_all()
    restored = []
    for file in files:
        with gzip.open(file, "rt", encoding="utf-8") as reader:
            restored.extend(json.loads(line) for line in reader)
    assert len(restored) == len(events)
    assert [row["exchange_ts_ms"] for row in restored] == list(range(1000, 1011))
    assert all(len({row["connection_id"] for row in
                    [json.loads(x) for x in gzip.open(file, "rt", encoding="utf-8")]}) == 1
               for file in files)



def test_post_gap_native_l2_snapshot_seals_damaged_prefix_and_recovers_clean_suffix(tmp_path):
    import gzip

    writer = PartitionedTickDatasetWriter(tmp_path, rotate_bytes=10_000_000)
    def book(ts, seq, previous, kind="UPDATE"):
        tick = envelope("okx_public_ws", "l2Book", "BTC-USDT-SWAP", ts)
        tick.event_kind = kind
        tick.sequence = seq
        tick.parsed_summary = {"prev_sequence": previous}
        return tick
    ticks = [
        book(1000, 10, -1),
        book(1001, 11, 10),
        book(1002, 15, 13),  # authenticated predecessor gap: 11 != 13.
        book(1003, 20, -1, "SNAPSHOT"),  # genuine source re-anchor.
        book(1004, 21, 20),
    ]
    assert len(writer.append_batch_records(ticks)) == 5
    shards = writer.rotate_all()
    assert len(shards) == 2
    manifests = [build_manifest_from_tick_shard(
        p, collector_version="recovery-test",
    ) for p in shards]
    assert [v["event_count"] for v in manifests] == [3, 2]
    assert manifests[0]["integrity"]["gap_count"] > 0
    assert manifests[0]["replay_compatible"] is False
    assert manifests[1]["integrity"]["gap_count"] == 0
    assert manifests[1]["replay_compatible"] is True
    all_rows = []
    for p in shards:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            all_rows.extend(json.loads(line) for line in fh)
    assert [row["received_ts_ms"] for row in all_rows] == [
        1005, 1006, 1007, 1008, 1009,
    ]


def test_post_gap_no_snapshot_remains_one_bad_shard(tmp_path):
    writer = PartitionedTickDatasetWriter(tmp_path, rotate_bytes=10_000_000)
    a = envelope("gate_public_ws", "l2Book", "BTC_USDT", 1000)
    b = envelope("gate_public_ws", "l2Book", "BTC_USDT", 1001)
    c = envelope("gate_public_ws", "l2Book", "BTC_USDT", 1002)
    a.sequence = 10
    b.sequence = 15
    b.parsed_summary = {"first_update_id": 14}
    c.sequence = 16
    c.parsed_summary = {"first_update_id": 16}
    writer.append_batch_records([a, b, c])
    shards = writer.rotate_all()
    assert len(shards) == 1
    manifest = build_manifest_from_tick_shard(shards[0], collector_version="recovery-test")
    assert manifest["integrity"]["gap_count"] > 0
    assert manifest["replay_compatible"] is False
