from __future__ import annotations

from hl_observer.collection.bybit_market_data import BybitMarketState, parse_bybit_linear_instruments
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
