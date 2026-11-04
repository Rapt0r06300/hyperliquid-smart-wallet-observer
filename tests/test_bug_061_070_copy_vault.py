from __future__ import annotations

from hl_observer.collection.coin_universe import validate_okx_linear_usdt_swap
from hl_observer.collection.native_venue_market import DESYNC
from hl_observer.collection.okx_market_data import OkxMarketState, okx_book_checksum, parse_okx_swap_instruments


def _book_payload(*, seq: int, prev: int, bids=None, asks=None, channel="books5", epoch=None):
    payload = {
        "arg": {"channel": channel, "instId": "BTC-USDT-SWAP"},
        "data": [{
            "ts": str(seq * 100),
            "seqId": seq,
            "prevSeqId": prev,
            "bids": bids or [["100", "1"]],
            "asks": asks or [["101", "1"]],
        }],
    }
    if epoch is not None:
        payload["_alina_transport"] = {"subscription_epoch": epoch}
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


def test_bug061_prev_sequence_discordance_is_named_and_fail_closed() -> None:
    state = OkxMarketState("BTC-USDT-SWAP")
    assert state.apply(_book_payload(seq=10, prev=-1), receive_ts_ms=1_001) != DESYNC
    assert state.apply(_book_payload(seq=12, prev=8), receive_ts_ms=1_003) == DESYNC
    assert state.reason == "PREV_SEQUENCE_DISCORDANT"
    assert not state.book_ready


def test_bug062_sequence_equal_to_prev_is_rejected_even_on_first_frame() -> None:
    state = OkxMarketState("BTC-USDT-SWAP")
    assert state.apply(_book_payload(seq=7, prev=7), receive_ts_ms=701) == DESYNC
    assert state.reason == "SEQUENCE_EQUALS_PREVIOUS"


def test_bug063_checksum_mismatch_quarantines_book() -> None:
    state = OkxMarketState("BTC-USDT-SWAP")
    payload = _book_payload(seq=1, prev=-1)
    payload["data"][0]["checksum"] = "123"  # deterministic bad protocol value
    assert state.apply(payload, receive_ts_ms=101) == DESYNC
    assert state.reason == "CHECKSUM_MISMATCH"
    assert not state.book_ready


def test_bug064_checksum_uses_venue_level_order_not_sorted_reconstruction() -> None:
    bids = [["100", "1"], ["99", "2"]]
    asks = [["101", "1"], ["102", "2"]]
    checksum = okx_book_checksum(bids, asks)
    state = OkxMarketState("BTC-USDT-SWAP")
    payload = _book_payload(
        seq=1,
        prev=-1,
        bids=list(reversed(bids)),
        asks=asks,
    )
    payload["data"][0]["checksum"] = checksum
    assert state.apply(payload, receive_ts_ms=101) == DESYNC
    assert state.reason == "CHECKSUM_MISMATCH"


def test_bug065_books_channels_cannot_be_mixed_without_reconnect() -> None:
    state = OkxMarketState("BTC-USDT-SWAP")
    assert state.apply(_book_payload(seq=1, prev=-1, channel="books5"), receive_ts_ms=101) != DESYNC
    assert state.apply(_book_payload(seq=2, prev=1, channel="books"), receive_ts_ms=102) == DESYNC
    assert state.reason == "CHANNEL_CHANGED"
    assert not state.book_ready


def test_bug066_late_snapshot_from_an_older_subscription_epoch_is_rejected() -> None:
    state = OkxMarketState("BTC-USDT-SWAP")
    assert state.apply(_book_payload(seq=10, prev=-1, epoch=2), receive_ts_ms=1_001) != DESYNC
    assert state.apply(_book_payload(seq=11, prev=-1, epoch=1), receive_ts_ms=1_002) == DESYNC
    assert state.reason == "STALE_SUBSCRIPTION_SNAPSHOT"
    assert not state.book_ready


def test_bug067_nominal_minimum_must_align_to_lot_size() -> None:
    ok, reason = validate_okx_linear_usdt_swap(_metadata(minSz="1.5", lotSz="1"))
    assert not ok
    assert reason == "MIN_SIZE_NOT_ALIGNED_TO_LOT"


def test_bug068_inverse_contracts_are_not_admitted_to_linear_copy_vault_feed() -> None:
    ok, reason = validate_okx_linear_usdt_swap(_metadata(ctType="inverse"))
    assert not ok
    assert reason == "NOT_LINEAR"


def test_bug069_margin_and_quote_currency_must_match_usdt_contract() -> None:
    ok, reason = validate_okx_linear_usdt_swap(_metadata(quoteCcy="USDC"))
    assert not ok
    assert reason == "QUOTE_CURRENCY_MISMATCH"


def test_bug070_delisted_instrument_is_excluded_from_discovery() -> None:
    payload = {"data": [_metadata(state="delisted"), _metadata()]}
    assert parse_okx_swap_instruments(payload) == [("BTC", "BTC-USDT-SWAP")]
