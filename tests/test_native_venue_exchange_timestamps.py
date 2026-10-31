from __future__ import annotations

from hl_observer.collection.bitget_market_data import BitgetMarketState
from hl_observer.collection.bybit_market_data import BybitMarketState
from hl_observer.collection.gate_market_data import GateMarketState
from hl_observer.collection.native_venue_market import NativeMarketSnapshot, UNMEASURABLE
from hl_observer.collection.okx_market_data import OkxMarketState


def test_bybit_ticker_does_not_refresh_the_orderbook_timestamp() -> None:
    state = BybitMarketState("BTCUSDT")
    state.apply_orderbook({
        "type": "snapshot", "ts": 1_000,
        "data": {"s": "BTCUSDT", "b": [["100", "1"]], "a": [["101", "1"]], "u": 1, "seq": 1},
    }, receive_ts_ms=1_010)

    state.apply_ticker({
        "ts": 2_000,
        "data": {"symbol": "BTCUSDT", "lastPrice": "100.5"},
    }, receive_ts_ms=2_010)

    snapshot = state.snapshot(now_ms=2_020)
    assert snapshot.exchange_ts_ms == 1_000
    assert snapshot.receive_ts_ms == 1_010
    assert snapshot.exploitable is False


def test_okx_ticker_does_not_refresh_the_orderbook_timestamp() -> None:
    state = OkxMarketState("BTC-USDT-SWAP")
    state.apply({
        "arg": {"channel": "books5", "instId": "BTC-USDT-SWAP"},
        "data": [{
            "ts": "1000", "seqId": 1, "prevSeqId": -1,
            "bids": [["100", "1", "0", "1"]],
            "asks": [["101", "1", "0", "1"]],
        }],
    }, receive_ts_ms=1_010)

    state.apply({
        "arg": {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
        "data": [{"instId": "BTC-USDT-SWAP", "last": "100.5", "ts": "2000"}],
    }, receive_ts_ms=2_010)

    snapshot = state.snapshot(now_ms=2_020)
    assert snapshot.exchange_ts_ms == 1_000
    assert snapshot.receive_ts_ms == 1_010
    assert snapshot.exploitable is False


def test_bitget_ticker_does_not_refresh_the_orderbook_timestamp() -> None:
    state = BitgetMarketState("BTCUSDT")
    state.apply({
        "arg": {"channel": "books5", "instId": "BTCUSDT"},
        "action": "snapshot",
        "data": [{
            "ts": "1000", "seq": "1",
            "bids": [["100", "1"]], "asks": [["101", "1"]],
        }],
    }, receive_ts_ms=1_010)

    state.apply({
        "arg": {"channel": "ticker", "instId": "BTCUSDT"},
        "data": [{"ts": "2000", "lastPr": "100.5"}],
    }, receive_ts_ms=2_010)

    snapshot = state.snapshot(now_ms=2_020)
    assert snapshot.exchange_ts_ms == 1_000
    assert snapshot.receive_ts_ms == 1_010
    assert snapshot.exploitable is False


def test_gate_book_without_exchange_time_is_not_exploitable() -> None:
    state = GateMarketState("BTC_USDT")
    state.apply_book({
        "full": True, "U": 1, "u": 1,
        "bids": [["100", "1"]], "asks": [["101", "1"]],
    }, receive_ts_ms=1_010)

    snapshot = state.snapshot(now_ms=1_020)
    assert snapshot.quality == UNMEASURABLE
    assert snapshot.exchange_ts_ms == 0
    assert snapshot.reason == "MISSING_EXCHANGE_TIMESTAMP"


def test_gate_book_without_receive_time_is_not_exploitable() -> None:
    state = GateMarketState("BTC_USDT")
    state.apply_book({
        "full": True, "U": 1, "u": 1, "time_ms": 1_000,
        "bids": [["100", "1"]], "asks": [["101", "1"]],
    })

    snapshot = state.snapshot(now_ms=1_020)
    assert snapshot.quality == UNMEASURABLE
    assert snapshot.receive_ts_ms == 0
    assert snapshot.reason == "MISSING_RECEIVE_TIMESTAMP"


def test_bitget_book_without_exchange_time_is_not_exploitable() -> None:
    state = BitgetMarketState("BTCUSDT")
    state.apply({
        "arg": {"channel": "books5", "instId": "BTCUSDT"},
        "action": "snapshot",
        "data": [{"seq": "1", "bids": [["100", "1"]], "asks": [["101", "1"]]}],
    }, receive_ts_ms=1_010)

    snapshot = state.snapshot(now_ms=1_020)
    assert snapshot.quality == UNMEASURABLE
    assert snapshot.exchange_ts_ms == 0
    assert snapshot.reason == "MISSING_EXCHANGE_TIMESTAMP"


def test_zero_exchange_timestamp_can_never_certify_a_snapshot() -> None:
    snapshot = NativeMarketSnapshot.build(
        venue="bitget", coin="BTC", exchange_symbol="BTCUSDT",
        bid=100, ask=101, exchange_ts_ms=0, receive_ts_ms=1_010,
        now_ms=1_020, stale_after_ms=1_000,
    )

    assert snapshot.quality == UNMEASURABLE
    assert snapshot.reason == "INVALID_MARKET_TIMESTAMPS"
