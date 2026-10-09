from __future__ import annotations

import asyncio
import json

import httpx

from hl_observer.collection.bybit_market_data import (
    BybitMarketState,
    BybitPublicClient,
    parse_bybit_linear_instruments,
)
from hl_observer.collection.native_venue_market import DESYNC, EXPLOITABLE


def test_bybit_snapshot_delta_and_ticker_normalize() -> None:
    state = BybitMarketState("BTCUSDT", stale_after_ms=1_000)
    status = state.apply_orderbook(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "snapshot",
            "ts": 1_000,
            "data": {
                "s": "BTCUSDT",
                "b": [["100", "2"], ["99", "3"]],
                "a": [["101", "4"], ["102", "5"]],
                "u": 10,
                "seq": 20,
            },
        },
        receive_ts_ms=1_010,
    )
    assert status == EXPLOITABLE

    state.apply_orderbook(
        {
            "type": "delta",
            "ts": 1_020,
            "data": {
                "s": "BTCUSDT",
                "b": [["100", "0"], ["100.5", "1"]],
                "a": [["101", "6"]],
                "u": 11,
                "seq": 21,
            },
        },
        receive_ts_ms=1_025,
    )
    state.apply_ticker(
        {
            "type": "delta",
            "ts": 1_030,
            "data": {
                "symbol": "BTCUSDT",
                "lastPrice": "100.8",
                "markPrice": "100.7",
                "indexPrice": "100.6",
                "volume24h": "12345",
                "openInterest": "555",
                "fundingRate": "0.0001",
                "fundingIntervalHour": "8",
            },
        },
        receive_ts_ms=1_035,
    )
    snap = state.snapshot(now_ms=1_100)
    assert snap.exploitable
    assert snap.bid == 100.5
    assert snap.ask == 101.0
    assert snap.last == 100.8
    assert snap.mark == 100.7
    assert snap.index == 100.6
    assert snap.volume_24h == 12345.0
    assert snap.open_interest == 555.0
    assert snap.funding_rate == 0.0001
    assert snap.funding_interval_hours == 8.0
    assert snap.sequence == 21
    assert snap.real_execution is False


def test_bybit_fail_closed_on_delta_before_snapshot_and_regression() -> None:
    state = BybitMarketState("ETHUSDT")
    assert (
        state.apply_orderbook(
            {"type": "delta", "data": {"s": "ETHUSDT", "b": [], "a": [], "u": 2, "seq": 2}},
            receive_ts_ms=100,
        )
        == DESYNC
    )

    state = BybitMarketState("ETHUSDT")
    state.apply_orderbook(
        {
            "type": "snapshot",
            "ts": 100,
            "data": {"s": "ETHUSDT", "b": [["10", "1"]], "a": [["11", "1"]], "u": 9, "seq": 9},
        },
        receive_ts_ms=101,
    )
    assert (
        state.apply_orderbook(
            {"type": "delta", "data": {"s": "ETHUSDT", "b": [], "a": [], "u": 8, "seq": 10}},
            receive_ts_ms=102,
        )
        == DESYNC
    )

    assert state.has_snapshot is False
    assert not state.bids and not state.asks
    # The apparent next delta must NOT restore an untrusted partial book.
    assert state.apply_orderbook(
        {"type": "delta", "data": {"s": "ETHUSDT", "b": [["10", "50"]], "a": [], "u": 10, "seq": 11}},
        receive_ts_ms=103,
    ) == DESYNC
    assert state.has_snapshot is False
    # Only a real exchange snapshot can restore an executable book.
    assert state.apply_orderbook(
        {"type": "snapshot", "ts": 104, "data": {
            "s": "ETHUSDT", "b": [["9", "2"]], "a": [["11", "3"]],
            "u": 12, "seq": 12,
        }},
        receive_ts_ms=105,
    ) == "EXPLOITABLE"
    assert state.has_snapshot is True


def test_bybit_discovery_keeps_usdt_perpetuals_only() -> None:
    payload = {
        "result": {
            "list": [
                {
                    "symbol": "BTCUSDT",
                    "baseCoin": "BTC",
                    "quoteCoin": "USDT",
                    "settleCoin": "USDT",
                    "status": "Trading",
                    "contractType": "LinearPerpetual",
                },
                {
                    "symbol": "ETHUSDC",
                    "baseCoin": "ETH",
                    "quoteCoin": "USDC",
                    "settleCoin": "USDC",
                    "status": "Trading",
                    "contractType": "LinearPerpetual",
                },
                {
                    "symbol": "SOLUSDT",
                    "baseCoin": "SOL",
                    "quoteCoin": "USDT",
                    "settleCoin": "USDT",
                    "status": "Closed",
                    "contractType": "LinearPerpetual",
                },
            ]
        }
    }
    assert parse_bybit_linear_instruments(payload) == [("BTC", "BTCUSDT")]


def test_bybit_discovery_retains_replay_critical_instrument_metadata(monkeypatch) -> None:
    client = BybitPublicClient()
    rows = [
        {
            "symbol": "BTCUSDT",
            "baseCoin": "BTC",
            "quoteCoin": "USDT",
            "settleCoin": "USDT",
            "status": "Trading",
            "contractType": "LinearPerpetual",
            "fundingInterval": 480,
            "priceFilter": {"tickSize": "0.1"},
            "lotSizeFilter": {
                "qtyStep": "0.001",
                "minOrderQty": "0.001",
                "minNotionalValue": "5",
            },
        }
    ]
    monkeypatch.setattr(
        client,
        "fetch_instrument_metadata",
        lambda **_kwargs: [dict(row) for row in rows],
    )

    assert client.discover_usdt_perpetuals() == [("BTC", "BTCUSDT")]
    assert client.last_instrument_metadata[0]["priceFilter"]["tickSize"] == "0.1"
    assert client.last_instrument_metadata[0]["lotSizeFilter"]["qtyStep"] == "0.001"
    assert client.last_instrument_metadata[0]["fundingInterval"] == 480


def test_bybit_discovery_falls_back_to_documented_bytick_domain(monkeypatch) -> None:
    seen: list[str] = []

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def get(self, url, params=None):
            seen.append(str(url))
            if str(url).startswith("https://api.bybit.com"):
                raise httpx.ConnectError("primary blocked")
            assert str(url).startswith("https://api.bytick.com")
            return FakeResponse(
                {
                    "retCode": 0,
                    "result": {
                        "list": [
                            {
                                "symbol": "BTCUSDT",
                                "baseCoin": "BTC",
                                "quoteCoin": "USDT",
                                "settleCoin": "USDT",
                                "status": "Trading",
                                "contractType": "LinearPerpetual",
                            }
                        ],
                        "nextPageCursor": "",
                    },
                }
            )

    monkeypatch.setattr(
        "hl_observer.collection.bybit_market_data.httpx.Client",
        FakeClient,
    )
    client = BybitPublicClient()

    assert client.discover_usdt_perpetuals() == [("BTC", "BTCUSDT")]
    assert seen[0].startswith("https://api.bybit.com")
    assert seen[1].startswith("https://api.bytick.com")
    assert client.last_rest_base_url == "https://api.bytick.com"
    assert client.last_rest_error == ""

def test_bybit_clock_falls_back_to_unauthenticated_public_ws_pong(monkeypatch) -> None:
    sent_payloads = []

    class FakeSocket:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def send(self, raw: str) -> None:
            sent_payloads.append(json.loads(raw))

        async def recv(self) -> str:
            return json.dumps(
                {
                    "req_id": "ignored",
                    "op": "pong",
                    "args": ["1675418560633"],
                    "conn_id": "clock-test",
                }
            )

    seen_urls = []

    def fake_connect(url, *_args, **_kwargs):
        seen_urls.append(str(url))
        if str(url).startswith("wss://stream.bybit.com"):
            raise OSError("primary WS blocked")
        assert str(url).startswith("wss://stream.bytick.com")
        return FakeSocket()

    monkeypatch.setattr(
        "hl_observer.collection.bybit_market_data.websockets.connect",
        fake_connect,
    )
    client = BybitPublicClient()
    monkeypatch.setattr(
        client,
        "server_time_ms",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("REST blocked")),
    )
    moments = iter([1675418560.620, 1675418560.620, 1675418560.640])
    monkeypatch.setattr(
        "hl_observer.collection.bybit_market_data.time.time",
        lambda: next(moments),
    )

    sample = client.measure_clock_sync(timeout_s=1.0)

    assert sent_payloads
    assert sent_payloads[0]["op"] == "ping"
    assert "auth" not in sent_payloads[0]
    assert sample.server_ts_ms == 1675418560633
    assert sample.rtt_ms == 20.0
    assert sample.offset_ms == 3.0
    assert seen_urls == [
        "wss://stream.bybit.com/v5/public/option",
        "wss://stream.bybit.com/v5/public/spread",
        "wss://stream.bytick.com/v5/public/option",
    ]
    assert (
        client.last_clock_source
        == "websocket_public_ping:stream.bytick.com:option"
    )
    assert client.last_clock_ws_url == "wss://stream.bytick.com/v5/public/option"
    assert client.last_clock_error == ""

def test_bybit_market_stream_falls_back_to_official_bytick_domain(monkeypatch) -> None:
    seen_urls = []

    class FakeSocket:
        latency = 0.01

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def send(self, _raw: str) -> None:
            return None

        async def recv(self) -> str:
            return json.dumps(
                {
                    "topic": "orderbook.200.BTCUSDT",
                    "type": "snapshot",
                    "ts": 1672304484978,
                    "data": {
                        "s": "BTCUSDT",
                        "b": [["100", "1"]],
                        "a": [["101", "1"]],
                        "u": 1,
                        "seq": 1,
                    },
                    "cts": 1672304484976,
                }
            )

    def fake_connect(url, *_args, **_kwargs):
        seen_urls.append(str(url))
        if str(url).startswith("wss://stream.bybit.com"):
            raise OSError("primary WS blocked")
        assert str(url).startswith("wss://stream.bytick.com")
        return FakeSocket()

    monkeypatch.setattr(
        "hl_observer.collection.bybit_market_data.websockets.connect",
        fake_connect,
    )
    monkeypatch.setattr(
        "hl_observer.collection.bybit_market_data.compute_backoff_delay",
        lambda **_kwargs: type("Delay", (), {"delay_seconds": 0.0})(),
    )
    client = BybitPublicClient()

    async def scenario() -> None:
        stream = client.messages(["BTCUSDT"])
        payload = await anext(stream)
        await stream.aclose()
        assert payload["topic"] == "orderbook.200.BTCUSDT"
        assert payload["_alina_transport"]["ws_url"] == (
            "wss://stream.bytick.com/v5/public/linear"
        )

    asyncio.run(scenario())
    assert seen_urls == [
        "wss://stream.bybit.com/v5/public/linear",
        "wss://stream.bytick.com/v5/public/linear",
    ]
    assert client.last_ws_url == "wss://stream.bytick.com/v5/public/linear"

