from __future__ import annotations

import asyncio
import gzip
import json

import httpx

from hl_observer.collection.bitget_market_data import BitgetMarketState
from hl_observer.collection.gate_market_data import GateMarketState
from hl_observer.collection.native_funding_history import (
    fetch_bitget_funding_settlements,
    fetch_gate_funding_settlements,
)
from hl_observer.collection.native_market_tape import native_tick_envelope
from hl_observer.collection.native_venue_market import DESYNC
from hl_observer.collection.trade_reconciliation import (
    reconcile_bitget_trade_shard,
    reconcile_gate_trade_shard,
)
from tools.collect_cloud_window import _replay_grade_coverage_report


def _transport() -> dict:
    return {
        "connection_id": "test-conn",
        "receive_wall_ts_ms": 2_000,
        "receive_mono_ns": 123_456,
        "transport_rtt_ms": 8.0,
        "clock_offset_ms": -2.0,
    }


def test_gate_rich_public_channels_are_taped() -> None:
    common = {"_alina_transport": _transport()}
    cases = [
        (
            {"channel": "futures.book_ticker", "event": "update", "result": {"s": "BTC_USDT", "b": "100", "a": "101", "t": 1995}, **common},
            "bbo",
        ),
        (
            {"channel": "futures.trades", "event": "update", "result": [{"id": 42, "contract": "BTC_USDT", "create_time_ms": 1995, "price": "100", "size": 1}], **common},
            "trades",
        ),
        (
            {"channel": "futures.tickers", "event": "update", "result": [{"contract": "BTC_USDT", "last": "100", "mark_price": "100.1"}], **common},
            "ticker",
        ),
        (
            {"channel": "futures.contract_stats", "event": "update", "result": [{"contract": "BTC_USDT", "time_ms": 1995, "open_interest": "50"}], **common},
            "open_interest",
        ),
        (
            {"channel": "futures.public_liquidates", "event": "update", "result": [{"contract": "BTC_USDT", "time_ms": 1995, "price": "99", "size": "-2"}], **common},
            "liquidations",
        ),
    ]
    for payload, family in cases:
        envelope = native_tick_envelope("gate", payload)
        assert envelope is not None
        assert envelope.channel == family
        assert envelope.instrument == "BTC_USDT"


def test_bitget_bbo_liquidation_and_vwap_depth_evidence() -> None:
    bbo = native_tick_envelope(
        "bitget",
        {
            "arg": {"instType": "USDT-FUTURES", "channel": "books1", "instId": "BTCUSDT"},
            "data": [{"ts": "1995", "seq": "10", "bids": [["100", "2"]], "asks": [["101", "2"]]}],
            "_alina_transport": _transport(),
        },
    )
    assert bbo is not None
    assert bbo.channel == "bbo"
    assert bbo.parsed_summary["depth_curve_replay_ready"] is True
    assert bbo.parsed_summary["vwap_target_quote_notionals_usd"] == [10, 50, 100, 250, 500, 1000]

    liquidation = native_tick_envelope(
        "bitget",
        {
            "arg": {"instType": "USDT-FUTURES", "channel": "liquidation", "instId": "BTCUSDT"},
            "data": [{"symbol": "BTCUSDT", "side": "sell", "price": "99", "amount": "2", "ts": "1995"}],
            "_alina_transport": _transport(),
        },
    )
    assert liquidation is not None
    assert liquidation.channel == "liquidations"


def test_gate_and_bitget_gap_detection_is_fail_closed() -> None:
    gate = GateMarketState("BTC_USDT")
    gate.apply_book({"U": 10, "u": 10, "b": [["100", "1"]], "a": [["101", "1"]]}, receive_ts_ms=1000)
    assert gate.apply_book({"U": 12, "u": 12, "b": [["100", "2"]], "a": []}, receive_ts_ms=1010) == DESYNC
    assert gate.gap_count == 1

    bitget = BitgetMarketState("BTCUSDT")
    bitget.apply(
        {"arg": {"channel": "books", "instId": "BTCUSDT"}, "data": [{"seq": "10", "bids": [["100", "1"]], "asks": [["101", "1"]]}]},
        receive_ts_ms=1000,
    )
    assert bitget.apply(
        {"arg": {"channel": "books", "instId": "BTCUSDT"}, "data": [{"seq": "12", "pseq": "9", "bids": [["100", "2"]], "asks": []}]},
        receive_ts_ms=1010,
    ) == DESYNC
    assert bitget.gap_count == 1


def test_gate_and_bitget_funding_history_are_bounded() -> None:
    async def scenario() -> None:
        async def gate_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"t": 2, "r": "0.0001"}, {"t": 9, "r": "0.0002"}])

        gate_client = httpx.AsyncClient(
            base_url="https://api.gateio.ws/api/v4",
            transport=httpx.MockTransport(gate_handler),
        )
        gate_rows = await fetch_gate_funding_settlements(
            ["BTC_USDT"], start_ms=1000, end_ms=5000, http_client=gate_client
        )
        await gate_client.aclose()
        assert [row.exchange_ts_ms for row in gate_rows] == [2000]

        async def bitget_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "code": "00000",
                    "data": [
                        {"symbol": "BTCUSDT", "fundingRate": "0.0001", "fundingTime": "2000"},
                        {"symbol": "BTCUSDT", "fundingRate": "0.0002", "fundingTime": "9000"},
                    ],
                },
            )

        bitget_client = httpx.AsyncClient(
            base_url="https://api.bitget.com",
            transport=httpx.MockTransport(bitget_handler),
        )
        bitget_rows = await fetch_bitget_funding_settlements(
            ["BTCUSDT"], start_ms=1000, end_ms=5000, http_client=bitget_client
        )
        await bitget_client.aclose()
        assert [row.exchange_ts_ms for row in bitget_rows] == [2000]

    asyncio.run(scenario())


def test_gate_and_bitget_exact_trade_reconciliation(tmp_path) -> None:
    gate_path = tmp_path / "gate.jsonl.gz"
    with gzip.open(gate_path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"raw_payload": {"channel": "futures.trades", "result": [{"id": 7, "contract": "BTC_USDT", "create_time_ms": 1000}]}}) + "\n")
    bitget_path = tmp_path / "bitget.jsonl.gz"
    with gzip.open(bitget_path, "wt", encoding="utf-8") as handle:
        handle.write(json.dumps({"raw_payload": {"arg": {"channel": "trade", "instId": "BTCUSDT"}, "data": [{"tradeId": "8", "ts": "1000"}]}}) + "\n")

    async def scenario() -> None:
        async def gate_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"id": 7, "contract": "BTC_USDT", "create_time_ms": 1000}])
        gate_client = httpx.AsyncClient(base_url="https://api.gateio.ws/api/v4", transport=httpx.MockTransport(gate_handler))
        gate_report = await reconcile_gate_trade_shard(
            gate_path, symbol="BTC_USDT", start_ms=1000, end_ms=1100, client=gate_client
        )
        await gate_client.aclose()
        assert gate_report["status"] == "MATCHED"

        async def bitget_handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"code": "00000", "data": [{"tradeId": "8", "ts": "1000"}]})
        bitget_client = httpx.AsyncClient(base_url="https://api.bitget.com", transport=httpx.MockTransport(bitget_handler))
        bitget_report = await reconcile_bitget_trade_shard(
            bitget_path, symbol="BTCUSDT", start_ms=1000, end_ms=1100, client=bitget_client
        )
        await bitget_client.aclose()
        assert bitget_report["status"] == "MATCHED"

    asyncio.run(scenario())


def test_replay_grade_coverage_uses_actual_published_families() -> None:
    manifests = []
    for family in ("l2Book", "bbo", "trades", "ticker", "instrument_metadata"):
        manifests.append(
            {
                "venue": "bitget",
                "symbol": "BTCUSDT",
                "family": family,
                "event_count": 1,
                "integrity": {
                    "missing_monotonic_count": 0,
                    "missing_timestamp_count": 0,
                    "gap_count": 0,
                    "regression_count": 0,
                },
            }
        )
    manifests.append(
        {
            "venue": "bitget",
            "symbol": "__VENUE__",
            "family": "clock_sync",
            "event_count": 1,
            "integrity": {},
        }
    )
    report = _replay_grade_coverage_report(manifests, {"bitget": ["BTCUSDT"]})
    assert report["complete"] is True
    broken = [row for row in manifests if row["family"] != "bbo"]
    report = _replay_grade_coverage_report(broken, {"bitget": ["BTCUSDT"]})
    assert report["complete"] is False
    assert report["per_venue"]["bitget"]["missing_families_by_symbol"]["BTCUSDT"] == ["bbo"]
