from __future__ import annotations

from hl_observer.collection.native_venue_market import DESYNC, EXPLOITABLE
from hl_observer.collection.okx_market_data import OkxMarketState, parse_okx_swap_instruments


def test_okx_books5_and_metrics_normalize() -> None:
    state = OkxMarketState("BTC-USDT-SWAP", stale_after_ms=1_000)
    status = state.apply(
        {
            "arg": {"channel": "books5", "instId": "BTC-USDT-SWAP"},
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
    assert status == EXPLOITABLE

    state.apply(
        {
            "arg": {"channel": "tickers", "instId": "BTC-USDT-SWAP"},
            "data": [{"instId": "BTC-USDT-SWAP", "last": "100.8", "vol24h": "12345", "ts": "1020"}],
        },
        receive_ts_ms=1_025,
    )
    state.apply(
        {
            "arg": {"channel": "open-interest", "instId": "BTC-USDT-SWAP"},
            "data": [{"instId": "BTC-USDT-SWAP", "oi": "555", "ts": "1030"}],
        },
        receive_ts_ms=1_035,
    )
    state.apply(
        {
            "arg": {"channel": "funding-rate", "instId": "BTC-USDT-SWAP"},
            "data": [
                {
                    "instId": "BTC-USDT-SWAP",
                    "fundingRate": "0.0002",
                    "fundingTime": "0",
                    "nextFundingTime": "28800000",
                    "ts": "1040",
                }
            ],
        },
        receive_ts_ms=1_045,
    )
    state.apply(
        {
            "arg": {"channel": "mark-price", "instId": "BTC-USDT-SWAP"},
            "data": [{"instId": "BTC-USDT-SWAP", "markPx": "100.7", "ts": "1050"}],
        },
        receive_ts_ms=1_055,
    )
    snap = state.snapshot(now_ms=1_100)
    assert snap.exploitable
    assert snap.bid == 100.0
    assert snap.ask == 101.0
    assert snap.last == 100.8
    assert snap.mark == 100.7
    assert snap.volume_24h == 12345.0
    assert snap.open_interest == 555.0
    assert snap.funding_rate == 0.0002
    assert snap.funding_interval_hours == 8.0
    assert snap.sequence == 10
    assert snap.real_execution is False


def test_okx_sequence_gap_is_fail_closed() -> None:
    state = OkxMarketState("ETH-USDT-SWAP")
    state.apply(
        {
            "arg": {"channel": "books5", "instId": "ETH-USDT-SWAP"},
            "data": [
                {"ts": "1", "seqId": 10, "prevSeqId": -1, "bids": [["10", "1", "0", "1"]], "asks": [["11", "1", "0", "1"]]}
            ],
        },
        receive_ts_ms=2,
    )
    assert (
        state.apply(
            {
                "arg": {"channel": "books5", "instId": "ETH-USDT-SWAP"},
                "data": [
                    {"ts": "3", "seqId": 12, "prevSeqId": 8, "bids": [["10", "1", "0", "1"]], "asks": [["11", "1", "0", "1"]]}
                ],
            },
            receive_ts_ms=4,
        )
        == DESYNC
    )


def test_okx_discovery_keeps_live_usdt_swaps_only() -> None:
    payload = {
        "data": [
            {"instId": "BTC-USDT-SWAP", "instType": "SWAP", "settleCcy": "USDT", "ctValCcy": "BTC", "state": "live"},
            {"instId": "ETH-USDC-SWAP", "instType": "SWAP", "settleCcy": "USDC", "ctValCcy": "ETH", "state": "live"},
            {"instId": "SOL-USDT-SWAP", "instType": "SWAP", "settleCcy": "USDT", "ctValCcy": "SOL", "state": "suspend"},
        ]
    }
    assert parse_okx_swap_instruments(payload) == [("BTC", "BTC-USDT-SWAP")]
