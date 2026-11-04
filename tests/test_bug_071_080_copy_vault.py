from __future__ import annotations

from hl_observer.collection.coin_universe import (
    quantize_okx_price,
    validate_okx_linear_usdt_swap,
    validate_okx_paper_notional,
)
from hl_observer.collection.native_venue_market import DESYNC, EXPLOITABLE, UNMEASURABLE
from hl_observer.collection.okx_market_data import OkxMarketState, OkxPublicClient


def _book(*, seq: int, bids=None, asks=None, source=None):
    payload = {
        "arg": {"channel": "books5", "instId": "BTC-USDT-SWAP"},
        "data": [{
            "ts": str(seq * 100),
            "seqId": seq,
            "prevSeqId": -1,
            "bids": bids or [["100", "1"]],
            "asks": asks or [["101", "1"]],
        }],
    }
    if source is not None:
        payload["_alina_transport"] = {"book_source": source}
    return payload


def _metadata(**overrides):
    row = {
        "instId": "BTC-USDT-SWAP",
        "instType": "SWAP",
        "state": "live",
        "ctType": "linear",
        "settleCcy": "USDT",
        "quoteCcy": "USDT",
        "ctValCcy": "BTC",
        "ctVal": "0.01",
        "ctMult": "1",
        "lotSz": "1",
        "minSz": "1",
        "tickSz": "0.1",
    }
    row.update(overrides)
    return row


def test_bug071_minimum_size_cannot_exceed_paper_notional() -> None:
    ok, reason = validate_okx_paper_notional(
        _metadata(minSz="3"), reference_price="100", paper_notional_usd="2"
    )
    assert not ok
    assert reason == "MIN_SIZE_EXCEEDS_PAPER_NOTIONAL"


def test_bug072_repricing_is_quantized_to_tick_without_float_drift() -> None:
    assert quantize_okx_price("100.07", "0.1", side="buy") == 100.0
    assert quantize_okx_price("100.01", "0.1", side="sell") == 100.1
    assert quantize_okx_price("nan", "0.1") is None


def test_bug073_suspended_status_is_not_admitted() -> None:
    ok, reason = validate_okx_linear_usdt_swap(_metadata(state="suspend"))
    assert not ok
    assert reason == "NOT_LIVE"


def test_bug074_interleaved_symbol_delta_cannot_mutate_another_state() -> None:
    state = OkxMarketState("BTC-USDT-SWAP")
    payload = _book(seq=1)
    payload["data"][0]["instId"] = "ETH-USDT-SWAP"
    assert state.apply(payload, receive_ts_ms=101) == DESYNC
    assert state.reason == "SYMBOL_MISMATCH"
    assert not state.book_ready


def test_bug075_instrument_timestamps_must_be_milliseconds() -> None:
    ok, reason = validate_okx_linear_usdt_swap(_metadata(listTime="1700000000"))
    assert not ok
    assert reason == "INVALID_LISTTIME"


def test_bug076_crossed_book_is_not_exploitable() -> None:
    state = OkxMarketState("BTC-USDT-SWAP")
    assert state.apply(_book(seq=1, bids=[["102", "1"]], asks=[["101", "1"]]), receive_ts_ms=101) == UNMEASURABLE
    assert state.reason == "INVALID_BBO"


def test_bug077_rest_and_ws_book_sources_cannot_be_mixed() -> None:
    state = OkxMarketState("BTC-USDT-SWAP")
    assert state.apply(_book(seq=1, source="ws"), receive_ts_ms=101) == EXPLOITABLE
    assert state.apply(_book(seq=2, source="rest"), receive_ts_ms=102) == DESYNC
    assert state.reason == "BOOK_SOURCE_CHANGED"


def test_bug078_maintenance_notice_is_ignored_without_mutating_book() -> None:
    state = OkxMarketState("BTC-USDT-SWAP")
    assert state.apply(_book(seq=1), receive_ts_ms=101) == EXPLOITABLE
    before = state.snapshot(now_ms=102)
    assert state.apply({"event": "notice", "msg": "maintenance"}, receive_ts_ms=103) == EXPLOITABLE
    after = state.snapshot(now_ms=104)
    assert after.bid == before.bid and after.ask == before.ask


def test_bug079_subscription_batches_preserve_every_argument() -> None:
    client = OkxPublicClient()
    expected = client.subscription_args(["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
    batches = client.subscription_batches(["BTC-USDT-SWAP", "ETH-USDT-SWAP"], max_args=2)
    assert all(0 < len(batch) <= 2 for batch in batches)
    assert [arg for batch in batches for arg in batch] == expected


def test_bug080_duplicate_snapshot_sequence_cannot_replace_prices_without_delta() -> None:
    state = OkxMarketState("BTC-USDT-SWAP")
    assert state.apply(_book(seq=1), receive_ts_ms=101) == EXPLOITABLE
    assert state.apply(_book(seq=1, bids=[["99", "9"]], asks=[["102", "9"]]), receive_ts_ms=102) == DESYNC
    assert state.reason == "DUPLICATE_SNAPSHOT_SEQUENCE"
    assert not state.book_ready
