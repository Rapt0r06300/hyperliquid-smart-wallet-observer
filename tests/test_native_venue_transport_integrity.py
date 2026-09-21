from __future__ import annotations

from hl_observer.collection.bybit_market_data import BybitMarketState
from hl_observer.collection.native_venue_market import DESYNC
from hl_observer.collection.okx_market_data import OkxMarketState


def test_bybit_prefers_matching_engine_time_and_tracks_transport() -> None:
    state = BybitMarketState("BTCUSDT")
    state.apply_orderbook(
        {
            "type": "snapshot",
            "ts": 1_005,
            "cts": 1_000,
            "_alina_transport": {
                "connection_id": "bybit-test",
                "receive_wall_ts_ms": 1_010,
                "receive_mono_ns": 123_000,
                "transport_rtt_ms": 8.5,
                "clock_offset_ms": -2.0,
            },
            "data": {
                "s": "BTCUSDT",
                "b": [["100", "1"]],
                "a": [["101", "1"]],
                "u": 10,
                "seq": 20,
            },
        }
    )
    snap = state.snapshot(now_ms=1_020)
    assert snap.exchange_ts_ms == 1_000
    assert snap.receive_ts_ms == 1_010
    assert snap.receive_mono_ns == 123_000
    assert snap.connection_id == "bybit-test"
    assert snap.transport_rtt_ms == 8.5
    assert snap.clock_offset_ms == -2.0


def test_bybit_update_id_gap_fails_closed() -> None:
    state = BybitMarketState("BTCUSDT")
    state.apply_orderbook(
        {
            "type": "snapshot",
            "cts": 1_000,
            "data": {
                "s": "BTCUSDT",
                "b": [["100", "1"]],
                "a": [["101", "1"]],
                "u": 10,
                "seq": 20,
            },
        },
        receive_ts_ms=1_010,
    )
    status = state.apply_orderbook(
        {
            "type": "delta",
            "cts": 1_020,
            "data": {
                "s": "BTCUSDT",
                "b": [["100", "2"]],
                "a": [],
                "u": 12,
                "seq": 22,
            },
        },
        receive_ts_ms=1_030,
    )
    assert status == DESYNC
    assert state.integrity.gaps == 1


def test_okx_gap_counter_is_preserved_in_snapshot() -> None:
    state = OkxMarketState("BTC-USDT-SWAP")
    state.apply(
        {
            "arg": {"channel": "books5", "instId": "BTC-USDT-SWAP"},
            "data": [
                {
                    "ts": "1000",
                    "seqId": 10,
                    "prevSeqId": -1,
                    "bids": [["100", "1"]],
                    "asks": [["101", "1"]],
                }
            ],
        },
        receive_ts_ms=1_010,
    )
    status = state.apply(
        {
            "arg": {"channel": "books5", "instId": "BTC-USDT-SWAP"},
            "data": [
                {
                    "ts": "1020",
                    "seqId": 12,
                    "prevSeqId": 8,
                    "bids": [["100", "1"]],
                    "asks": [["101", "1"]],
                }
            ],
        },
        receive_ts_ms=1_030,
    )
    assert status == DESYNC
    assert state.snapshot(now_ms=1_040).gap_count == 1
