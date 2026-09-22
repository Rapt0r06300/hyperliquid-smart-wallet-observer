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
        "okx": "PEPE-USDT-SWAP"
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
    assert index["repository"] == "Rapt0r06300/alina-smartflow-datasets-v2"
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
        )
    )
    assert len(sink.rows) == 1
    record = sink.rows[0].as_record(written_ts_ms=1020)
    summary = record["parsed_summary"]
    assert summary["clock_offset_ms"] == -3.5
    assert summary["clock_probe_rtt_ms"] == 12.0
    assert summary["transport_rtt_ms"] == 8.0


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
