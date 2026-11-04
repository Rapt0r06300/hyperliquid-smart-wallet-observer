from __future__ import annotations

from hl_observer.collection.bybit_market_data import BybitMarketState
from hl_observer.collection.native_venue_market import DESYNC, EXPLOITABLE


def _snapshot(
    *,
    topic: str = "orderbook.50.BTCUSDT",
    update_id: int = 10,
    sequence: int = 20,
    bids: list[list[str]] | None = None,
    asks: list[list[str]] | None = None,
    cts: int = 1_000,
    ts: int | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "topic": topic,
        "type": "snapshot",
        "cts": cts,
        "data": {
            "s": "BTCUSDT",
            "b": bids or [["100", "1"]],
            "a": asks or [["101", "1"]],
            "u": update_id,
            "seq": sequence,
        },
    }
    if ts is not None:
        payload["ts"] = ts
    return payload


def test_bug041_repeated_l1_snapshot_with_same_update_id_reanchors_cleanly() -> None:
    state = BybitMarketState("BTCUSDT")

    assert state.apply_orderbook(
        _snapshot(topic="orderbook.1.BTCUSDT", update_id=7, sequence=7),
        receive_ts_ms=1_010,
    ) == EXPLOITABLE
    assert state.apply_orderbook(
        _snapshot(
            topic="orderbook.1.BTCUSDT",
            update_id=7,
            sequence=7,
            bids=[["99", "2"]],
            asks=[["100", "2"]],
        ),
        receive_ts_ms=1_011,
    ) == EXPLOITABLE

    assert state.stream_depth == 1
    assert state.bids == {99.0: 2.0}


def test_bug042_delta_update_id_one_marks_a_bybit_service_restart() -> None:
    state = BybitMarketState("BTCUSDT")
    state.apply_orderbook(_snapshot(), receive_ts_ms=1_010)

    status = state.apply_orderbook(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "delta",
            "data": {"s": "BTCUSDT", "b": [], "a": [], "u": 1, "seq": 21},
        },
        receive_ts_ms=1_020,
    )

    assert status == DESYNC
    assert state.reason == "BYBIT_SERVICE_RESTART"
    assert state.has_snapshot is False


def test_bug043_delta_before_snapshot_is_rejected() -> None:
    state = BybitMarketState("BTCUSDT")

    status = state.apply_orderbook(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "delta",
            "data": {"s": "BTCUSDT", "b": [], "a": [], "u": 2, "seq": 2},
        },
        receive_ts_ms=1_000,
    )

    assert status == DESYNC
    assert state.reason == "DELTA_BEFORE_SNAPSHOT"


def test_bug044_zero_delta_size_removes_a_level() -> None:
    state = BybitMarketState("BTCUSDT")
    state.apply_orderbook(_snapshot(), receive_ts_ms=1_010)

    assert state.apply_orderbook(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "delta",
            "cts": 1_020,
            "data": {"s": "BTCUSDT", "b": [["100", "0"]], "a": [], "u": 11, "seq": 21},
        },
        receive_ts_ms=1_020,
    ) == "UNMEASURABLE"
    assert 100.0 not in state.bids


def test_bug045_delta_can_add_a_new_level_without_rebuilding_other_levels() -> None:
    state = BybitMarketState("BTCUSDT")
    state.apply_orderbook(_snapshot(), receive_ts_ms=1_010)

    state.apply_orderbook(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "delta",
            "cts": 1_020,
            "data": {"s": "BTCUSDT", "b": [["99", "3"]], "a": [], "u": 11, "seq": 21},
        },
        receive_ts_ms=1_020,
    )

    assert state.bids == {100.0: 1.0, 99.0: 3.0}


def test_bug046_matching_engine_cts_is_preferred_over_transport_ts() -> None:
    state = BybitMarketState("BTCUSDT")

    state.apply_orderbook(
        _snapshot(cts=1_000, ts=1_005),
        receive_ts_ms=1_010,
    )

    assert state.exchange_ts_ms == 1_000


def test_bug047_sequence_regression_invalidates_the_book() -> None:
    state = BybitMarketState("BTCUSDT")
    state.apply_orderbook(_snapshot(sequence=20), receive_ts_ms=1_010)

    status = state.apply_orderbook(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "delta",
            "cts": 1_020,
            "data": {"s": "BTCUSDT", "b": [], "a": [], "u": 9, "seq": 21},
        },
        receive_ts_ms=1_020,
    )

    assert status == DESYNC
    assert state.reason == "SEQUENCE_REGRESSION"


def test_bug048_cross_sequence_jump_is_not_silently_called_a_gap() -> None:
    state = BybitMarketState("BTCUSDT")
    state.apply_orderbook(_snapshot(sequence=20), receive_ts_ms=1_010)

    status = state.apply_orderbook(
        {
            "topic": "orderbook.50.BTCUSDT",
            "type": "delta",
            "cts": 1_020,
            "data": {"s": "BTCUSDT", "b": [], "a": [], "u": 11, "seq": 25},
        },
        receive_ts_ms=1_020,
    )

    assert status != DESYNC
    assert state.integrity.gaps == 0


def test_bug049_depth_one_stream_is_not_reported_as_depth_fifty() -> None:
    state = BybitMarketState("BTCUSDT")
    status = state.apply_orderbook(
        _snapshot(
            topic="orderbook.1.BTCUSDT",
            bids=[["100", "1"], ["99", "2"]],
            asks=[["101", "1"], ["102", "2"]],
        ),
        receive_ts_ms=1_010,
    )

    snap = state.snapshot(now_ms=1_020, depth=50)
    assert status == EXPLOITABLE
    assert state.stream_depth == 1
    assert len(snap.bids) == 1
    assert len(snap.asks) == 1


def test_bug050_unexpected_orderbook_topic_is_fail_closed() -> None:
    state = BybitMarketState("BTCUSDT")

    status = state.apply_orderbook(
        _snapshot(topic="ticker.BTCUSDT"),
        receive_ts_ms=1_010,
    )

    assert status == DESYNC
    assert state.reason == "UNEXPECTED_ORDERBOOK_TOPIC"
    assert state.has_snapshot is False
