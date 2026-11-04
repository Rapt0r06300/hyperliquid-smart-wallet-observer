from __future__ import annotations

from hl_observer.collection.bybit_market_data import (
    BybitMarketState,
    parse_bybit_linear_instruments,
)
from hl_observer.collection.native_venue_market import (
    DESYNC,
    EXPLOITABLE,
    STALE,
    UNMEASURABLE,
)


def _snapshot(
    *,
    symbol: str = "BTCUSDT",
    topic: str = "orderbook.50.BTCUSDT",
    update_id: int = 10,
    sequence: int = 20,
    bids: list[list[str]] | None = None,
    asks: list[list[str]] | None = None,
    connection_id: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "topic": topic,
        "type": "snapshot",
        "cts": 1_000,
        "data": {
            "seq": sequence,
            "a": asks if asks is not None else [["101", "1"]],
            "s": symbol,
            "u": update_id,
            "b": bids if bids is not None else [["100", "1"]],
        },
    }
    if connection_id is not None:
        payload["_alina_transport"] = {"connection_id": connection_id}
    return payload


def test_bug051_prelaunch_without_a_book_is_unmeasurable() -> None:
    state = BybitMarketState("BTCUSDT")

    snapshot = state.snapshot(now_ms=1_000)

    assert snapshot.exploitable is False
    assert snapshot.quality == UNMEASURABLE
    assert snapshot.reason == "NO_SNAPSHOT"


def test_bug052_json_message_key_order_does_not_change_parsing() -> None:
    state = BybitMarketState("BTCUSDT")
    payload = _snapshot()

    assert state.apply_orderbook(payload, receive_ts_ms=1_010) == EXPLOITABLE
    assert state.bids == {100.0: 1.0}
    assert state.asks == {101.0: 1.0}


def test_bug053_rpi_metadata_is_not_promoted_to_l2() -> None:
    state = BybitMarketState("BTCUSDT")
    payload = _snapshot()
    data = payload["data"]
    assert isinstance(data, dict)
    data["rpi"] = [["99.5", "999"]]

    assert state.apply_orderbook(payload, receive_ts_ms=1_010) == EXPLOITABLE
    assert state.bids == {100.0: 1.0}
    assert 99.5 not in state.bids


def test_bug054_reconnect_requires_a_new_snapshot_before_deltas() -> None:
    state = BybitMarketState("BTCUSDT")
    assert state.apply_orderbook(
        _snapshot(connection_id="conn-1"), receive_ts_ms=1_010
    ) == EXPLOITABLE

    status = state.apply_orderbook(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "delta",
            "data": {"s": "BTCUSDT", "b": [["100", "2"]], "a": [], "u": 11, "seq": 21},
            "_alina_transport": {"connection_id": "conn-2"},
        },
        receive_ts_ms=1_020,
    )

    assert status == DESYNC
    assert state.reason == "DELTA_BEFORE_SNAPSHOT"
    assert state.apply_orderbook(
        _snapshot(connection_id="conn-2"), receive_ts_ms=1_030
    ) == EXPLOITABLE


def test_bug055_message_symbol_change_is_fail_closed() -> None:
    state = BybitMarketState("BTCUSDT")

    status = state.apply_orderbook(
        _snapshot(symbol="ETHUSDT", topic="orderbook.50.BTCUSDT"),
        receive_ts_ms=1_010,
    )

    assert status == DESYNC
    assert state.reason == "SYMBOL_MISMATCH"


def test_bug056_fresh_ticker_cannot_hide_stale_l2() -> None:
    state = BybitMarketState("BTCUSDT", stale_after_ms=1_000)
    assert state.apply_orderbook(_snapshot(), receive_ts_ms=1_010) == EXPLOITABLE

    state.apply_ticker(
        {
            "ts": 1_900,
            "data": [{"symbol": "BTCUSDT", "lastPrice": "100.5"}],
        },
        receive_ts_ms=1_900,
    )

    snapshot = state.snapshot(now_ms=3_000)
    assert snapshot.quality == STALE
    assert snapshot.reason == "STALE_RECEIVE_AGE"


def test_bug057_repeated_delta_is_deduplicated_without_reapplying_mutation() -> None:
    state = BybitMarketState("BTCUSDT")
    state.apply_orderbook(_snapshot(), receive_ts_ms=1_010)
    first = {
        "topic": "orderbook.50.BTCUSDT",
        "type": "delta",
        "cts": 1_020,
        "data": {"s": "BTCUSDT", "b": [["100", "2"]], "a": [], "u": 11, "seq": 21},
    }
    repeated = {
        "topic": "orderbook.50.BTCUSDT",
        "type": "delta",
        "cts": 1_020,
        "data": {"s": "BTCUSDT", "b": [["100", "9"]], "a": [], "u": 11, "seq": 21},
    }

    state.apply_orderbook(first, receive_ts_ms=1_020)
    state.apply_orderbook(repeated, receive_ts_ms=1_030)

    assert state.bids == {100.0: 2.0}
    assert state.integrity.duplicates == 1


def test_bug058_nonfinite_or_negative_levels_are_rejected() -> None:
    state = BybitMarketState("BTCUSDT")

    assert state.apply_orderbook(
        _snapshot(
            bids=[["100", "1"], ["101", "nan"], ["102", "inf"], ["103", "-1"]],
            asks=[["101", "1"], ["102", "nan"], ["103", "-1"]],
        ),
        receive_ts_ms=1_010,
    ) == EXPLOITABLE

    assert state.bids == {100.0: 1.0}
    assert state.asks == {101.0: 1.0}


def test_bug059_linear_instrument_mapping_excludes_spot_and_wrong_settlement() -> None:
    payload = {
        "result": {
            "list": [
                {"symbol": "BTCUSDT", "baseCoin": "BTC", "quoteCoin": "USDT", "settleCoin": "USDT", "status": "Trading", "contractType": "LinearPerpetual"},
                {"symbol": "BTCUSDC", "baseCoin": "BTC", "quoteCoin": "USDC", "settleCoin": "USDC", "status": "Trading", "contractType": "LinearPerpetual"},
                {"symbol": "BTCUSDT-SPOT", "baseCoin": "BTC", "quoteCoin": "USDT", "settleCoin": "", "status": "Trading", "contractType": "Spot"},
                {"symbol": "ETHUSDT", "baseCoin": "ETH", "quoteCoin": "USDT", "settleCoin": "USDT", "status": "Settled", "contractType": "LinearPerpetual"},
            ]
        }
    }

    assert parse_bybit_linear_instruments(payload) == [("BTC", "BTCUSDT")]


def test_bug060_empty_depth_cannot_feed_an_active_signal() -> None:
    state = BybitMarketState("BTCUSDT")

    status = state.apply_orderbook(
        _snapshot(bids=[], asks=[]),
        receive_ts_ms=1_010,
    )
    snapshot = state.snapshot(now_ms=1_020)

    assert status == UNMEASURABLE
    assert snapshot.exploitable is False
    assert snapshot.quality == UNMEASURABLE
    assert snapshot.reason == "INVALID_BBO"
