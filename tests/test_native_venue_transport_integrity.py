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


def test_bybit_standard_depth_does_not_invent_gap_from_nonconsecutive_u() -> None:
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
    assert status != DESYNC
    assert state.integrity.gaps == 0


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


def test_okx_books_reconstructs_400_level_style_deltas() -> None:
    state = OkxMarketState("BTC-USDT-SWAP")
    status = state.apply(
        {
            "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
            "action": "snapshot",
            "data": [
                {
                    "ts": "1000",
                    "seqId": 10,
                    "prevSeqId": -1,
                    "bids": [["100", "2", "0", "1"], ["99", "3", "0", "1"]],
                    "asks": [["101", "4", "0", "1"], ["102", "5", "0", "1"]],
                }
            ],
        },
        receive_ts_ms=1_010,
    )
    assert status != DESYNC
    assert state.book_ready

    status = state.apply(
        {
            "arg": {"channel": "books", "instId": "BTC-USDT-SWAP"},
            "action": "update",
            "data": [
                {
                    "ts": "1020",
                    "seqId": 11,
                    "prevSeqId": 10,
                    "bids": [["100", "0", "0", "0"], ["100.5", "1", "0", "1"]],
                    "asks": [["101", "6", "0", "1"]],
                }
            ],
        },
        receive_ts_ms=1_030,
    )
    assert status != DESYNC
    snap = state.snapshot(now_ms=1_040)
    assert snap.bid == 100.5
    assert snap.ask == 101.0
    assert len(snap.bids) == 2
    assert snap.asks[0].size == 6.0


def test_okx_books_gap_discards_reconstructed_book() -> None:
    state = OkxMarketState("ETH-USDT-SWAP")
    state.apply(
        {
            "arg": {"channel": "books", "instId": "ETH-USDT-SWAP"},
            "action": "snapshot",
            "data": [{
                "ts": "1000",
                "seqId": 10,
                "prevSeqId": -1,
                "bids": [["10", "1", "0", "1"]],
                "asks": [["11", "1", "0", "1"]],
            }],
        },
        receive_ts_ms=1_010,
    )
    status = state.apply(
        {
            "arg": {"channel": "books", "instId": "ETH-USDT-SWAP"},
            "action": "update",
            "data": [{
                "ts": "1020",
                "seqId": 12,
                "prevSeqId": 9,
                "bids": [["10", "2", "0", "1"]],
                "asks": [],
            }],
        },
        receive_ts_ms=1_030,
    )
    assert status == DESYNC
    assert not state.book_ready
    assert not state.book_bids
    assert not state.book_asks
