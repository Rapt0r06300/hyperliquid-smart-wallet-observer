from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _module():
    spec = importlib.util.spec_from_file_location(
        "collect_cloud_window",
        ROOT / "tools" / "collect_cloud_window.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_hyperliquid_l2_frame_becomes_replay_tick() -> None:
    m = _module()
    tick = m._hyperliquid_envelope(
        {
            "channel": "l2Book",
            "data": {
                "coin": "BTC",
                "time": 1000,
                "levels": [
                    [{"px": "100", "sz": "1"}],
                    [{"px": "101", "sz": "2"}],
                ],
            },
        },
        received_ts_ms=1010,
        receive_mono_ns=123456,
        connection_id="hl-test",
    )
    assert tick is not None
    assert tick.source_id == "hyperliquid_public_ws"
    assert tick.channel == "l2Book"
    assert tick.instrument == "BTC"
    assert tick.exchange_ts_ms == 1000
    assert tick.received_ts_ms == 1010
    assert tick.local_monotonic_ns == 123456


def test_hyperliquid_frame_carries_clock_probe_evidence() -> None:
    m = _module()
    tick = m._hyperliquid_envelope(
        {
            "channel": "bbo",
            "data": {
                "coin": "BTC",
                "time": 1000,
                "bbo": [
                    {"px": "100", "sz": "1", "n": 1},
                    {"px": "101", "sz": "2", "n": 1},
                ],
            },
        },
        received_ts_ms=1010,
        receive_mono_ns=123456,
        connection_id="hl-clock-test",
        clock_evidence={
            "clock_offset_ms": -1.5,
            "clock_probe_rtt_ms": 20.0,
        },
    )
    assert tick is not None
    assert tick.parsed_summary["clock_offset_ms"] == -1.5
    assert tick.parsed_summary["clock_probe_rtt_ms"] == 20.0


def test_sink_publishes_same_runner_cross_venue_capacity() -> None:
    m = _module()

    class Writer:
        pass

    sink = m.AsyncPartitionSink(Writer())
    left = m.capacity_tape_envelope(
        venue="bybit",
        instrument="BTCUSDT",
        bids=[[99, 4]],
        asks=[[100, 3]],
        exchange_ts_ms=1_990,
        received_ts_ms=2_000,
        receive_mono_ns=100,
        connection_id="bybit-1",
        sequence=10,
        quality="EXPLOITABLE",
        source_raw_l2_payload={"seq": 10},
    )
    right = m.capacity_tape_envelope(
        venue="okx",
        instrument="BTC-USDT-SWAP",
        bids=[[101, 2]],
        asks=[[102, 5]],
        exchange_ts_ms=1_992,
        received_ts_ms=2_003,
        receive_mono_ns=103,
        connection_id="okx-1",
        sequence=20,
        quality="EXPLOITABLE",
        source_raw_l2_payload={"seqId": 20},
    )
    assert left is not None and right is not None
    sink.emit(left)
    sink.emit(right)
    rows = []
    while not sink.queue.empty():
        rows.append(sink.queue.get_nowait())
    cross = [row for row in rows if row.channel == "cross_venue_capacity_tape"]
    assert len(cross) == 1
    assert cross[0].instrument == "BTC"
    assert cross[0].parsed_summary["directions"]["BUY_A_SELL_B"]["entry_simultaneous_capacity_usd"] == 202.0
    assert cross[0].provenance["derived"] is True
    assert cross[0].provenance["raw_l2_source_of_truth"] is True


def test_binance_bbo_keeps_update_id_and_transport_clock() -> None:
    m = _module()
    tick = m._binance_bbo_envelope(
        {
            "data": {
                "s": "BTCUSDT",
                "b": "100",
                "a": "101",
                "B": "2",
                "A": "3",
                "T": 1000,
                "u": 77,
            }
        },
        received_ts_ms=1010,
        receive_mono_ns=999,
        connection_id="bin-test",
    )
    assert tick is not None
    assert tick.channel == "bbo"
    assert tick.sequence == 77
    assert tick.exchange_ts_ms == 1000
    assert tick.connection_id == "bin-test"


def test_binance_bbo_carries_clock_probe_evidence() -> None:
    m = _module()
    tick = m._binance_bbo_envelope(
        {
            "data": {
                "s": "BTCUSDT",
                "b": "100",
                "a": "101",
                "T": 1000,
                "u": 77,
            }
        },
        received_ts_ms=1010,
        receive_mono_ns=999,
        connection_id="bin-test",
        clock_evidence={
            "clock_offset_ms": -2.5,
            "clock_probe_rtt_ms": 9.0,
        },
    )
    assert tick is not None
    assert tick.parsed_summary["clock_offset_ms"] == -2.5
    assert tick.parsed_summary["clock_probe_rtt_ms"] == 9.0


def test_binance_trade_preserves_exchange_trade_id() -> None:
    m = _module()
    tick = m._binance_trade_envelope(
        {
            "data": {
                "e": "trade",
                "s": "ETHUSDT",
                "p": "2000",
                "q": "0.5",
                "T": 1000,
                "t": 123,
                "m": True,
            }
        },
        received_ts_ms=1005,
        receive_mono_ns=100,
        connection_id="bin-trade-test",
    )
    assert tick is not None
    assert tick.channel == "trades"
    assert tick.sequence == 123
    assert tick.parsed_summary["aggressor_side"] == "SELL"


def test_binance_trade_carries_clock_probe_evidence() -> None:
    m = _module()
    tick = m._binance_trade_envelope(
        {
            "data": {
                "e": "aggTrade",
                "s": "ETHUSDT",
                "p": "2000",
                "q": "0.5",
                "T": 1000,
                "a": 123,
                "m": False,
            }
        },
        received_ts_ms=1005,
        receive_mono_ns=100,
        connection_id="bin-trade-test",
        clock_evidence={
            "clock_offset_ms": 3.0,
            "clock_probe_rtt_ms": 12.0,
        },
    )
    assert tick is not None
    assert tick.parsed_summary["clock_offset_ms"] == 3.0
    assert tick.parsed_summary["clock_probe_rtt_ms"] == 12.0


def test_plan_file_preserves_exact_exchange_symbols(tmp_path) -> None:
    m = _module()
    path = tmp_path / "plan.json"
    path.write_text(
        """{
  "coins": [
    {
      "coin": "PEPE",
      "symbols": {
        "hyperliquid": "PEPE",
        "binance": "1000PEPEUSDT",
        "bybit": "1000PEPEUSDT",
        "okx": "PEPE-USDT-SWAP",
        "gate": "PEPE_USDT",
        "bitget": "PEPEUSDT"
      }
    },
    {
      "coin": "HYPE",
      "symbols": {
        "hyperliquid": "HYPE",
        "bybit": "HYPEUSDT"
      }
    }
  ]
}
""",
        encoding="utf-8",
    )
    rows = m._load_plan_rows(path)
    assert rows[0]["coin"] == "PEPE"
    venue_lists = m._venue_lists(["HYPE", "PEPE"], rows)
    assert venue_lists["binance"] == ["1000PEPEUSDT"]
    assert venue_lists["bybit"] == ["1000PEPEUSDT", "HYPEUSDT"]
    assert venue_lists["hyperliquid"] == ["HYPE", "PEPE"]
    assert venue_lists["okx"] == ["PEPE-USDT-SWAP"]
    assert venue_lists["gate"] == ["PEPE_USDT"]
    assert venue_lists["bitget"] == ["PEPEUSDT"]


def test_bundle_index_is_publisher_compatible_and_counts_quality() -> None:
    m = _module()
    manifests = [
        {
            "dataset_id": "safe-1",
            "release_asset": "safe-1.jsonl.gz",
            "quality_status": "SAFE",
        },
        {
            "dataset_id": "partial-1",
            "release_asset": "partial-1.jsonl.gz",
            "quality_status": "PARTIAL",
        },
        {
            "dataset_id": "reject-1",
            "release_asset": "reject-1.jsonl.gz",
            "quality_status": "REJECT",
        },
    ]
    index = m._bundle_index(
        manifests,
        collector_version="a" * 40,
        collection_run_id="market-test-run",
        queue_drops={
            ("bybit_public_ws", "l2Book", "BTCUSDT"): 2,
            ("okx_public_ws", "l2Book", "BTC-USDT-SWAP"): 1,
        },
    )
    assert index["schema"] == "alina.dataset_bundle.v2"
    assert index["repository"] == "Rapt0r06300/hyperliquid-smart-wallet-observer"
    assert index["collection_run_id"] == "market-test-run"
    assert index["shard_count"] == 3
    assert index["safe_count"] == 1
    assert index["partial_count"] == 1
    assert index["reject_count"] == 1
    assert index["collection_queue_drops"] == 3
    assert index["manifests"] == [
        "manifests/safe-1.json",
        "manifests/partial-1.json",
        "manifests/reject-1.json",
    ]
    assert index["assets"] == [
        "assets/safe-1.jsonl.gz",
        "assets/partial-1.jsonl.gz",
        "assets/reject-1.jsonl.gz",
    ]


def test_hyperliquid_active_asset_ctx_is_preserved_without_fake_exchange_time() -> None:
    m = _module()
    tick = m._hyperliquid_envelope(
        {
            "channel": "activeAssetCtx",
            "data": {
                "coin": "BTC",
                "ctx": {
                    "markPx": "100.5",
                    "midPx": "100.4",
                    "oraclePx": "100.3",
                    "funding": "0.0001",
                    "openInterest": "1234",
                    "premium": "0.0002",
                    "dayNtlVlm": "5000000",
                },
            },
        },
        received_ts_ms=1010,
        receive_mono_ns=123456,
        connection_id="hl-ctx-test",
    )
    assert tick is not None
    assert tick.channel == "activeAssetCtx"
    assert tick.instrument == "BTC"
    assert tick.exchange_ts_ms is None
    assert tick.parsed_summary["mark_price"] == 100.5
    assert tick.parsed_summary["oracle_price"] == 100.3
    assert tick.parsed_summary["funding_rate"] == 0.0001
    assert tick.parsed_summary["open_interest"] == 1234.0


def test_cloud_native_frame_carries_clock_probe_evidence() -> None:
    import asyncio
    from types import SimpleNamespace

    m = _module()

    class Sink:
        def __init__(self) -> None:
            self.rows = []

        def emit(self, envelope) -> None:
            self.rows.append(envelope)

    class Client:
        def measure_clock_sync(self):
            return SimpleNamespace(
                offset_ms=-3.5,
                rtt_ms=12.0,
                server_ts_ms=1000,
                receive_wall_ts_ms=1010,
            )

        async def messages(self, _symbols):
            yield {
                "topic": "orderbook.200.BTCUSDT",
                "type": "snapshot",
                "cts": 1000,
                "data": {
                    "s": "BTCUSDT",
                    "b": [["100", "1"]],
                    "a": [["101", "1"]],
                    "u": 1,
                    "seq": 1,
                },
                "_alina_transport": {
                    "connection_id": "bybit-cloud-test",
                    "receive_wall_ts_ms": 1010,
                    "receive_mono_ns": 123,
                    "transport_rtt_ms": 8.0,
                },
            }

    sink = Sink()
    asyncio.run(
        m._native_with_clock_sync(
            "bybit",
            Client(),
            ["BTCUSDT"],
            sink,
            probe_interval_s=60,
            capacity_size_multipliers={"BTCUSDT": 1.0},
        )
    )
    assert {row.channel for row in sink.rows} == {"l2Book", "capacity_tape"}
    raw = next(row for row in sink.rows if row.channel == "l2Book")
    record = raw.as_record(written_ts_ms=1020)
    summary = record["parsed_summary"]
    assert summary["clock_offset_ms"] == -3.5
    assert summary["clock_probe_rtt_ms"] == 12.0
    assert summary["transport_rtt_ms"] == 8.0
    capacity = next(row for row in sink.rows if row.channel == "capacity_tape")
    assert capacity.parsed_summary["clock_offset_ms"] == -3.5
    assert capacity.parsed_summary["clock_probe_rtt_ms"] == 12.0
    assert capacity.parsed_summary["source_raw_l2_sha256"] == record["raw_sha256"]


def test_cloud_window_backfills_funding_per_venue_fail_closed(monkeypatch) -> None:
    import asyncio

    m = _module()

    class Sink:
        def __init__(self) -> None:
            self.rows = []

        def emit(self, envelope) -> None:
            self.rows.append(envelope)

    def row(source: str, instrument: str):
        return m.TickEnvelope(
            source_id=source,
            channel="funding_settlement",
            instrument=instrument,
            event_kind="EVENT",
            raw_payload={"fundingRate": "0.0001"},
            exchange_ts_ms=2_000,
            received_ts_ms=2_010,
            local_monotonic_ns=123,
            connection_id=None,
            sequence=1,
            provenance={
                "access": "read_only",
                "transport": "https",
                "authenticated": False,
            },
            parsed_summary={"funding_rate": 0.0001},
        )

    async def ok_hl(symbols, **_kwargs):
        assert symbols == ["BTC"]
        return [row("hyperliquid_public_rest", "BTC")]

    async def ok_binance(symbols, **_kwargs):
        assert symbols == ["BTCUSDT"]
        return [row("binance_usdm_public_rest", "BTCUSDT")]

    async def fail_bybit(_symbols, **_kwargs):
        raise RuntimeError("temporary upstream failure")

    async def ok_okx(symbols, **_kwargs):
        assert symbols == ["BTC-USDT-SWAP"]
        return [row("okx_public_rest", "BTC-USDT-SWAP")]

    monkeypatch.setattr(m, "fetch_hyperliquid_funding_settlements", ok_hl)
    monkeypatch.setattr(m, "fetch_binance_funding_settlements", ok_binance)
    monkeypatch.setattr(m, "fetch_bybit_funding_settlements", fail_bybit)
    monkeypatch.setattr(m, "fetch_okx_funding_settlements", ok_okx)

    sink = Sink()
    result = asyncio.run(
        m._collect_funding_settlements(
            {
                "hyperliquid": ["BTC"],
                "binance": ["BTCUSDT"],
                "bybit": ["BTCUSDT"],
                "okx": ["BTC-USDT-SWAP"],
            },
            sink,
            start_ms=1_000,
            end_ms=3_000,
        )
    )

    assert len(sink.rows) == 3
    assert all(item.channel == "funding_settlement" for item in sink.rows)
    assert result["hyperliquid"] == {"status": "OK", "records": 1}
    assert result["binance"] == {"status": "OK", "records": 1}
    assert result["okx"] == {"status": "OK", "records": 1}
    assert result["bybit"]["status"] == "ERROR"
    assert result["bybit"]["records"] == 0
    assert result["bybit"]["error"] == "RuntimeError"


def test_binance_aggtrade_is_separate_reconcilable_family() -> None:
    m = _module()
    tick = m._binance_trade_envelope(
        {
            "data": {
                "e": "aggTrade",
                "s": "BTCUSDT",
                "a": 500,
                "f": 700,
                "l": 702,
                "p": "65000",
                "q": "1.2",
                "T": 1000,
                "m": False,
            }
        },
        received_ts_ms=1005,
        receive_mono_ns=100,
        connection_id="bin-agg-test",
    )
    assert tick is not None
    assert tick.channel == "agg_trades"
    assert tick.sequence == 500
    assert tick.parsed_summary["aggregate_trade_id"] == 500
    assert tick.parsed_summary["first_trade_id"] == 700
    assert tick.parsed_summary["last_trade_id"] == 702
    assert tick.parsed_summary["aggressor_side"] == "BUY"


def test_native_transport_adds_receive_clock_when_client_has_none() -> None:
    import asyncio

    m = _module()

    class Client:
        async def messages(self, _symbols):
            yield {
                "arg": {
                    "instType": "USDT-FUTURES",
                    "channel": "trade",
                    "instId": "BTCUSDT",
                },
                "data": [{"ts": "1000", "price": "100", "size": "1"}],
            }

    class Sink:
        def __init__(self) -> None:
            self.rows = []

        def emit(self, row) -> None:
            self.rows.append(row)

    sink = Sink()
    asyncio.run(
        m._native_with_clock_sync(
            "bitget",
            Client(),
            ["BTCUSDT"],
            sink,
            probe_interval_s=60,
        )
    )
    assert len(sink.rows) == 1
    row = sink.rows[0]
    assert row.received_ts_ms > 0
    assert row.local_monotonic_ns is not None
    assert row.connection_id is not None
    assert row.connection_id.startswith("bitget-")


def test_l2_coverage_report_is_fail_closed_per_expected_symbol() -> None:
    m = _module()
    manifests = [
        {
            "venue": "hyperliquid",
            "family": "l2Book",
            "symbol": "BTC",
            "event_count": 5,
        },
        {
            "venue": "binance",
            "family": "l2Book",
            "symbol": "BTCUSDT",
            "event_count": 7,
        },
        {
            "venue": "bybit",
            "family": "l2Book",
            "symbol": "BTCUSDT",
            "event_count": 3,
        },
    ]
    coverage = m._l2_coverage_report(
        manifests,
        {
            "hyperliquid": ["BTC"],
            "binance": ["BTCUSDT"],
            "bybit": ["BTCUSDT", "ETHUSDT"],
            "okx": [],
            "gate": [],
            "bitget": [],
        },
    )
    assert coverage["complete"] is False
    assert coverage["expected_symbol_count"] == 4
    assert coverage["observed_symbol_count"] == 3
    assert coverage["missing_symbols"] == {"bybit": ["ETHUSDT"]}


def test_l2_coverage_report_accepts_complete_six_venue_coverage() -> None:
    m = _module()
    venue_symbols = {
        "hyperliquid": ["BTC"],
        "binance": ["BTCUSDT"],
        "bybit": ["BTCUSDT"],
        "okx": ["BTC-USDT-SWAP"],
        "gate": ["BTC_USDT"],
        "bitget": ["BTCUSDT"],
    }
    manifests = [
        {
            "venue": venue,
            "family": "l2Book",
            "symbol": symbols[0],
            "event_count": 1,
        }
        for venue, symbols in venue_symbols.items()
    ]
    coverage = m._l2_coverage_report(manifests, venue_symbols)
    assert coverage["complete"] is True
    assert coverage["required_venues"] == [
        "binance",
        "bitget",
        "bybit",
        "gate",
        "hyperliquid",
        "okx",
    ]
    assert coverage["expected_symbol_count"] == 6
    assert coverage["observed_symbol_count"] == 6
    assert coverage["missing_symbols"] == {}


def test_l2_gate_localizes_partial_missing_coverage() -> None:
    m = _module()
    coverage = {
        "expected_symbol_count": 6,
        "observed_symbol_count": 5,
        "missing_symbols": {"bybit": ["ETHUSDT"]},
    }
    assert m._l2_gate_failure_reason(coverage, required=True) is None


def test_l2_gate_rejects_a_completely_empty_l2_capture() -> None:
    m = _module()
    coverage = {
        "expected_symbol_count": 6,
        "observed_symbol_count": 0,
        "missing_symbols": {"hyperliquid": ["BTC"]},
    }
    assert m._l2_gate_failure_reason(coverage, required=True) == "L2_COLLECTION_EMPTY"



def test_gate_reconnect_rebootstraps_capacity_book() -> None:
    import asyncio
    from types import SimpleNamespace

    m = _module()

    class Sink:
        def __init__(self) -> None:
            self.rows = []

        def emit(self, envelope) -> None:
            self.rows.append(envelope)

    class Client:
        def __init__(self) -> None:
            self.bootstrap_calls = 0

        def measure_clock_sync(self):
            return SimpleNamespace(
                offset_ms=-1.0,
                rtt_ms=4.0,
                server_ts_ms=1000,
                receive_wall_ts_ms=1002,
            )

        def bootstrap_envelopes(self, _symbols):
            self.bootstrap_calls += 1
            seq = self.bootstrap_calls * 100
            ts = self.bootstrap_calls * 1000
            return [
                m.TickEnvelope(
                    source_id="gate_public_rest",
                    channel="l2Book",
                    instrument="BTC_USDT",
                    event_kind="SNAPSHOT",
                    raw_payload={
                        "id": seq,
                        "current": ts,
                        "bids": [{"p": "100", "s": "10"}],
                        "asks": [{"p": "101", "s": "10"}],
                    },
                    exchange_ts_ms=ts,
                    received_ts_ms=ts + 2,
                    local_monotonic_ns=seq,
                    connection_id=None,
                    sequence=seq,
                    provenance={"access": "read_only", "transport": "https"},
                    parsed_summary={},
                )
            ]

        async def messages(self, _symbols):
            yield {
                "channel": "futures.order_book_update",
                "event": "update",
                "result": {
                    "contract": "BTC_USDT",
                    "U": 101,
                    "u": 101,
                    "t": 1_010,
                    "b": [{"p": "100", "s": "11"}],
                    "a": [],
                },
                "_alina_transport": {
                    "connection_id": "gate-a",
                    "receive_wall_ts_ms": 1_012,
                    "receive_mono_ns": 1_001,
                    "transport_rtt_ms": 3.0,
                },
            }
            yield {
                "channel": "futures.order_book_update",
                "event": "update",
                "result": {
                    "contract": "BTC_USDT",
                    "U": 201,
                    "u": 201,
                    "t": 2_010,
                    "b": [{"p": "100", "s": "12"}],
                    "a": [],
                },
                "_alina_transport": {
                    "connection_id": "gate-b",
                    "receive_wall_ts_ms": 2_012,
                    "receive_mono_ns": 2_001,
                    "transport_rtt_ms": 3.0,
                },
            }

    client = Client()
    sink = Sink()
    asyncio.run(
        m._native_with_clock_sync(
            "gate",
            client,
            ["BTC_USDT"],
            sink,
            probe_interval_s=60,
            capacity_size_multipliers={"BTC_USDT": 0.001},
        )
    )
    assert client.bootstrap_calls == 2
    raw_books = [row for row in sink.rows if row.channel == "l2Book"]
    capacity = [row for row in sink.rows if row.channel == "capacity_tape"]
    assert len(raw_books) == 4
    assert len(capacity) == 4
    assert all(
        row.parsed_summary["size_multiplier_to_base"] == 0.001
        for row in capacity
    )



def test_async_sink_backpressures_instead_of_dropping_raw_frames():
    import asyncio
    import types
    m = _module()

    class Writer:
        def __init__(self):
            self.rows = []

        def append_batch_records(self, batch):
            self.rows.extend(batch)
            return list(batch)

    async def exercise():
        writer = Writer()
        sink = m.AsyncPartitionSink(writer, max_queue=1, batch_size=1)
        one = types.SimpleNamespace(
            source_id="okx_public_ws", channel="trades", instrument="BTCUSDT",
            parsed_summary={},
        )
        two = types.SimpleNamespace(
            source_id="okx_public_ws", channel="trades", instrument="ETHUSDT",
            parsed_summary={},
        )
        await sink.emit_async(one)
        pending = asyncio.create_task(sink.emit_async(two))
        await asyncio.sleep(0)
        assert not pending.done()
        assert sink.backpressure_events == 1
        worker = asyncio.create_task(sink.run())
        await pending
        await sink.close()
        await worker
        assert sink.accepted == sink.persisted == 2
        assert sink.drops == {}
        assert writer.rows == [one, two]

    asyncio.run(exercise())


def test_legacy_sink_never_pairs_a_derived_capacity_frame_that_was_dropped():
    import types
    m = _module()

    class Writer:
        pass

    sink = m.AsyncPartitionSink(Writer(), max_queue=1)
    first = types.SimpleNamespace(
        source_id="bybit_public_ws", channel="capacity_tape",
        instrument="BTCUSDT", parsed_summary={"coin": "BTC", "venue": "bybit"},
    )
    second = types.SimpleNamespace(
        source_id="okx_public_ws", channel="capacity_tape",
        instrument="BTCUSDT", received_ts_ms=1002,
        parsed_summary={"coin": "BTC", "venue": "okx"},
    )
    sink.emit(first)
    sink.emit(second)
    assert sink.accepted == 1
    assert sink.drops[sink.key(second)] == 1
    assert ("BTC", "okx") not in sink._latest_capacity



def test_batched_cloud_partition_writer_keeps_all_raw_evidence_durable(tmp_path):
    import gzip
    import json

    m = _module()
    writer = m.PartitionedTickDatasetWriter(
        tmp_path, rotate_bytes=5_000_000, flush_every=128,
    )
    ticks = [
        m._hyperliquid_envelope(
            {"channel": "l2Book", "data": {
                "coin": "BTC", "time": 1000 + i,
                "levels": [[{"px": "100", "sz": "1"}], [{"px": "101", "sz": "2"}]],
            }},
            received_ts_ms=1010 + i, receive_mono_ns=123456 + i,
            connection_id="hl-test",
        )
        for i in range(4)
    ]
    assert all(t is not None for t in ticks)
    assert len(writer.append_batch_records(ticks[:2])) == 2
    assert len(writer.append_batch_records(ticks[2:])) == 2
    live = list(tmp_path.glob("**/*.current.jsonl"))
    assert len(live) == 1
    assert len([json.loads(line) for line in live[0].read_text().splitlines()]) == 4
    [shard] = writer.rotate_all()
    with gzip.open(shard, "rt", encoding="utf-8") as stream:
        restored = [json.loads(line) for line in stream]
    assert len(restored) == 4
    assert [r["received_ts_ms"] for r in restored] == [1010, 1011, 1012, 1013]
    receipt = json.loads(shard.with_name(shard.name + ".manifest.json").read_text())
    assert receipt["event_count"] == 4
    assert receipt["sha256"]
    assert writer.stats()["records_written"] == 4



def test_cross_venue_derived_receive_clock_does_not_invent_exchange_timestamp(tmp_path):
    import gzip
    import json
    m = _module()

    def one(venue, exchange, received, mono):
        return m.capacity_tape_envelope(
            venue=venue,
            instrument="BTCUSDT" if venue == "bybit" else "BTC-USDT-SWAP",
            bids=[[100, 3]], asks=[[101, 3]],
            exchange_ts_ms=exchange, received_ts_ms=received,
            receive_mono_ns=mono,
            connection_id=venue + "-1", sequence=10,
            quality="EXPLOITABLE",
            source_raw_l2_payload={"sequence": 10, "exchange": exchange},
        )

    first = m.cross_venue_capacity_envelope(
        one("bybit", 1020, 1040, 1_000_000_000),
        one("okx", 1015, 1041, 1_000_000_010),
    )
    second = m.cross_venue_capacity_envelope(
        one("bybit", 1017, 1050, 1_000_000_100),
        one("okx", 1009, 1051, 1_000_000_110),
    )
    assert first is not None and second is not None
    assert first.exchange_ts_ms is None
    assert second.exchange_ts_ms is None
    assert second.received_ts_ms > first.received_ts_ms
    assert second.provenance["timestamp_semantics"] == "receive_observation_time_only"
    assert first.parsed_summary["source_legs"]
    assert all(leg["exchange_ts_ms"] is not None for leg in first.parsed_summary["source_legs"])

    writer = m.PartitionedTickDatasetWriter(tmp_path)
    writer.append_batch_records([first, second])
    [shard] = writer.rotate_all()
    manifest = m.build_manifest_from_tick_shard(shard, collector_version="test")
    assert manifest["integrity"]["regression_count"] == 0
    assert manifest["integrity"]["missing_timestamp_count"] == 0
    assert manifest["synchronization"]["first_exchange_ts_ms"] is None
    assert manifest["replay_compatible"] is True
    with gzip.open(shard, "rt", encoding="utf-8") as source:
        raw = [json.loads(line) for line in source]
    assert len(raw) == 2
    assert all(row["exchange_ts_ms"] is None for row in raw)



def test_queue_loss_affects_only_temporally_impacted_shards():
    m = _module()
    sample = lambda start, end: {
        "source": "gate_public_ws", "family": "bbo", "symbol": "BTC_USDT",
        "start_ts_ms": start, "end_ts_ms": end,
        "synchronization": {"connection_ids": ["gate-1"]},
    }
    rows = [sample(1000, 1999), sample(2000, 2999), sample(3000, 3999)]
    key = ("gate_public_ws", "bbo", "BTC_USDT")
    attributed = m.attribute_queue_drops(
        rows, {key: 3}, {(*key, "gate-1", 2): 3},
    )
    assert attributed == [0, 3, 0]


def test_queue_loss_unknown_time_is_conservatively_fail_closed():
    m = _module()
    key = ("gate_public_ws", "trades", "ETH_USDT")
    rows = [
        {"source": key[0], "family": key[1], "symbol": key[2],
         "start_ts_ms": 1000, "end_ts_ms": 1500,
         "synchronization": {"connection_ids": ["gate-1"]}},
        {"source": key[0], "family": key[1], "symbol": key[2],
         "start_ts_ms": 2000, "end_ts_ms": 2500,
         "synchronization": {"connection_ids": ["gate-1"]}},
    ]
    assert m.attribute_queue_drops(
        rows, {key: 1}, {(*key, "gate-1", -1): 1}
    ) == [1, 1]


def test_orphaned_queue_loss_preserves_other_markets_but_reports_missing_partition():
    m = _module()
    key = ("bitget_public_ws", "l2Book", "BTCUSDT")
    other = {
        "source": "gate_public_ws", "family": "trades",
        "symbol": "ETH_USDT", "start_ts_ms": 2000, "end_ts_ms": 2999,
        "synchronization": {"connection_ids": ["gate-ok"]},
    }
    assert m.attribute_queue_drops([other], {key: 1}, {(*key, "conn-1", 2): 1}) == [0]
    assert m.orphaned_queue_drops([other], {key: 1}) == {
        "bitget_public_ws|l2Book|BTCUSDT": 1
    }
    assert m.attribute_queue_drops([], {key: 1}, {(*key, "conn-1", 2): 1}) == []


def test_sync_sink_records_queue_loss_clock_and_connection():
    m = _module()
    class Writer:
        pass
    sink = m.AsyncPartitionSink(Writer(), max_queue=1)
    one = m._hyperliquid_envelope(
        {"channel": "bbo", "data": {
            "coin": "BTC", "time": 1000,
            "bbo": [{"px": "100", "sz": "1"}, {"px": "101", "sz": "1"}],
        }},
        received_ts_ms=1200, receive_mono_ns=100, connection_id="conn-1",
    )
    two = m._hyperliquid_envelope(
        {"channel": "bbo", "data": {
            "coin": "BTC", "time": 2200,
            "bbo": [{"px": "100", "sz": "1"}, {"px": "101", "sz": "1"}],
        }},
        received_ts_ms=2300, receive_mono_ns=200, connection_id="conn-1",
    )
    sink.emit(one)
    sink.emit(two)
    assert sink.drops[("hyperliquid_public_ws", "bbo", "BTC")] == 1
    assert sink.drop_windows[("hyperliquid_public_ws", "bbo", "BTC", "conn-1", 2)] == 1



def test_gate_book_gap_invalidates_capacity_until_authoritative_snapshot():
    from hl_observer.collection.gate_market_data import GateMarketState

    state = GateMarketState(contract="BTC_USDT")
    base = {
        "full": True, "id": 100, "current": 1_000,
        "bids": [{"p": "100", "s": "10"}],
        "asks": [{"p": "101", "s": "10"}],
    }
    assert state.apply_book(base, receive_ts_ms=1_010) == "EXPLOITABLE"
    assert state.sequence == 100
    assert state.apply_book({"U": 101, "u": 101, "b": [["100", "12"]], "a": []},
                            receive_ts_ms=1_020) == "EXPLOITABLE"
    assert state.apply_book({"U": 105, "u": 105, "b": [["100", "99"]], "a": []},
                            receive_ts_ms=1_030) == "DESYNC"
    assert state.reason == "SEQUENCE_GAP"
    assert state.gap_count == 1
    assert state.sequence is None
    assert not state.bids and not state.asks
    assert state.apply_book({"U": 106, "u": 106, "b": [["100", "99"]], "a": []},
                            receive_ts_ms=1_040) == "UNMEASURABLE"
    assert state.reason == "DELTA_BEFORE_SNAPSHOT"
    assert state.gap_count == 1
    assert state.apply_book({
        "full": True, "id": 200, "current": 2_000,
        "bids": [{"p": "99", "s": "8"}],
        "asks": [{"p": "101", "s": "8"}],
    }, receive_ts_ms=2_010) == "EXPLOITABLE"
    assert state.sequence == 200
    assert state.gap_count == 1


def test_gate_missing_official_base_refuses_orphan_delta():
    from hl_observer.collection.gate_market_data import GateMarketState
    state = GateMarketState(contract="BTC_USDT")
    assert state.apply_book({
        "U": 1, "u": 1, "b": [["100", "10"]], "a": [["101", "10"]],
    }, receive_ts_ms=1000) == "UNMEASURABLE"
    assert state.sequence is None
    assert state.reason == "DELTA_BEFORE_SNAPSHOT"


def test_gate_gap_schedules_bounded_single_contract_rebootstrap_without_cutting_raw():
    import asyncio
    from types import SimpleNamespace

    m = _module()
    class Sink:
        def __init__(self):
            self.rows = []
        def emit(self, envelope):
            self.rows.append(envelope)
    class Client:
        def __init__(self):
            self.bootstrap_calls = []
        def measure_clock_sync(self):
            return SimpleNamespace(
                offset_ms=0, rtt_ms=1, server_ts_ms=1000,
                receive_wall_ts_ms=1001,
            )
        def bootstrap_envelopes(self, contracts):
            self.bootstrap_calls.append(tuple(contracts))
            seq = 100 if len(self.bootstrap_calls) == 1 else 200
            return [m.TickEnvelope(
                source_id="gate_public_rest", channel="l2Book",
                instrument=contracts[0], event_kind="SNAPSHOT",
                raw_payload={
                    "id": seq, "current": seq * 10,
                    "bids": [{"p": "100", "s": "10"}],
                    "asks": [{"p": "101", "s": "10"}],
                }, exchange_ts_ms=seq * 10,
                received_ts_ms=seq * 10 + 2, local_monotonic_ns=seq,
                connection_id=None, sequence=seq,
                provenance={"access": "read_only", "transport": "https"},
                parsed_summary={},
            )]
        async def messages(self, _symbols):
            def delta(first, last):
                return {
                    "channel": "futures.order_book_update", "event": "update",
                    "result": {"contract": "BTC_USDT", "U": first, "u": last,
                               "t": last * 10,
                               "b": [{"p": "100", "s": "12"}], "a": []},
                    "_alina_transport": {
                        "connection_id": "gate-a",
                        "receive_wall_ts_ms": last * 10 + 3,
                        "receive_mono_ns": last * 1000,
                    },
                }
            yield delta(101, 101)
            yield delta(105, 105)  # real sequence gap, stays in RAW.
            await asyncio.sleep(0.08)  # bounded on-demand REST reanchor.
            yield delta(201, 201)

    client, sink = Client(), Sink()
    asyncio.run(m._native_with_clock_sync(
        "gate", client, ["BTC_USDT"], sink, probe_interval_s=60,
        capacity_size_multipliers={"BTC_USDT": 0.001},
    ))
    assert client.bootstrap_calls == [("BTC_USDT",), ("BTC_USDT",)]
    assert len([r for r in sink.rows if r.source_id == "gate_public_ws"
                and r.channel == "l2Book"]) == 3
    assert len([r for r in sink.rows if r.channel == "capacity_tape"]) >= 3


def test_native_ws_batches_are_persisted_as_individual_trade_events():
    """A native two-trade WS message must create two immutable replay records."""
    import asyncio
    from types import SimpleNamespace

    m = _module()

    class Client:
        def measure_clock_sync(self):
            return SimpleNamespace(
                offset_ms=0, rtt_ms=1, server_ts_ms=1000,
                receive_wall_ts_ms=1001,
            )

        async def messages(self, _symbols):
            yield {
                "topic": "publicTrade.BTCUSDT",
                "ts": 1005,
                "data": [
                    {"s": "BTCUSDT", "i": "trade-1", "T": 1000,
                     "p": "100", "v": "1", "S": "Buy"},
                    {"s": "BTCUSDT", "i": "trade-2", "T": 1001,
                     "p": "101", "v": "2", "S": "Sell"},
                ],
            }

    class Sink:
        def __init__(self):
            self.rows = []

        def emit(self, envelope):
            self.rows.append(envelope)

    sink = Sink()
    asyncio.run(m._native_with_clock_sync(
        "bybit", Client(), ["BTCUSDT"], sink, probe_interval_s=60,
    ))
    trades = [row for row in sink.rows if row.channel == "trades"]
    assert len(trades) == 2
    assert [row.parsed_summary["event_count"] for row in trades] == [1, 1]
    assert [row.parsed_summary["source_batch_index"] for row in trades] == [0, 1]
    assert [row.parsed_summary["source_batch_size"] for row in trades] == [2, 2]
    assert len({row.parsed_summary["source_batch_sha256"] for row in trades}) == 1
    assert trades[0].raw_payload["data"][0]["i"] == "trade-1"
    assert trades[1].raw_payload["data"][0]["i"] == "trade-2"
    assert all(row.provenance["access"] == "read_only" for row in trades)


def test_hyperliquid_batches_preserve_exact_trade_evidence():
    m = _module()
    original = {
        "channel": "trades",
        "data": [
            {"coin": "BTC", "tid": 101, "time": 1000, "px": "100", "sz": "1"},
            {"coin": "BTC", "tid": 102, "time": 1001, "px": "101", "sz": "2"},
        ],
    }
    rows = m._hyperliquid_envelopes(
        original, received_ts_ms=1100, receive_mono_ns=500,
        connection_id="hl-1",
    )
    assert len(rows) == 2
    assert [row.raw_payload["data"][0]["tid"] for row in rows] == [101, 102]
    assert [row.exchange_ts_ms for row in rows] == [1000, 1001]
    assert [row.parsed_summary["event_count"] for row in rows] == [1, 1]
    assert [row.parsed_summary["source_batch_index"] for row in rows] == [0, 1]
    assert len({row.parsed_summary["source_batch_sha256"] for row in rows}) == 1
    assert len(original["data"]) == 2
    assert all(row.provenance["access"] == "read_only" for row in rows)


def test_hyperliquid_malformed_batch_not_silently_truncated():
    m = _module()
    payload = {"channel": "trades", "data": [
        {"coin": "BTC", "tid": 101, "time": 1000},
        {"tid": 102, "time": 1001},
    ]}
    rows = m._hyperliquid_envelopes(
        payload, received_ts_ms=1100, receive_mono_ns=500,
        connection_id="hl-1",
    )
    assert len(rows) == 1
    assert rows[0].parsed_summary["event_count"] == 2
    assert len(rows[0].raw_payload["data"]) == 2


def test_native_malformed_trade_batch_stays_whole_and_unverified():
    from hl_observer.collection.native_market_tape import native_tick_envelopes

    frame = {
        "topic": "publicTrade.BTCUSDT",
        "ts": 1005,
        "data": [
            {"s": "BTCUSDT", "i": "trade-1", "T": 1000},
            "malformed",
        ],
        "_alina_transport": {
            "receive_wall_ts_ms": 1010,
            "receive_mono_ns": 100000,
            "connection_id": "bybit-1",
        },
    }
    rows = native_tick_envelopes("bybit", frame)
    assert len(rows) == 1
    assert rows[0].parsed_summary["event_count"] == 2
    assert rows[0].raw_payload["data"][1] == "malformed"
    assert rows[0].parsed_summary.get("source_batch_index") is None
