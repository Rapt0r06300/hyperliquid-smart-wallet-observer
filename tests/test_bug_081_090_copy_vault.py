from __future__ import annotations

from hl_observer.collection import gate_market_data as gate
from hl_observer.collection.bitget_market_data import BitgetMarketState
from hl_observer.collection.gate_market_data import GateMarketState, parse_gate_contracts, validate_gate_contract
from hl_observer.collection.native_venue_market import DESYNC, EXPLOITABLE, UNMEASURABLE


def _full(*, seq: int = 1, timestamp_key: str = "t", timestamp=1_700_000_000, **extra):
    bids = extra.pop("bids", [["100", "1"]])
    asks = extra.pop("asks", [["101", "1"]])
    payload = {
        "full": True,
        "id": seq,
        timestamp_key: timestamp,
        "b": bids,
        "a": asks,
    }
    payload.update(extra)
    return payload


def _delta(*, first: int, last: int, timestamp=1_700_000_001, **extra):
    payload = {"U": first, "u": last, "t": timestamp, "b": [["100", "2"]], "a": []}
    payload.update(extra)
    return payload


def _contract(**overrides):
    row = {"name": "BTC_USDT", "in_delisting": False, "type": "direct"}
    row.update(overrides)
    return row


def test_bug081_gate_timestamp_fields_keep_seconds_and_milliseconds_distinct() -> None:
    assert gate._gate_timestamp_ms({"t": 1_700_000_000}) == 1_700_000_000_000
    assert gate._gate_timestamp_ms({"time_ms": 1_700_000_000_000}) == 1_700_000_000_000
    assert gate._gate_timestamp_ms({"time_ms": 1_700_000_000}) is None


def test_bug082_gate_full_snapshot_requires_a_sequence_anchor() -> None:
    state = GateMarketState("BTC_USDT")
    assert state.apply_book({"full": True, "t": 1_700_000_000, "b": [[100, 1]], "a": [[101, 1]]}) == UNMEASURABLE
    assert state.reason == "MISSING_OR_INVALID_SEQUENCE"


def test_bug083_gate_delta_before_snapshot_is_not_executable() -> None:
    state = GateMarketState("BTC_USDT")
    assert state.apply_book(_delta(first=1, last=1)) == UNMEASURABLE
    assert state.reason == "DELTA_BEFORE_SNAPSHOT"


def test_bug084_gate_reconnect_requires_a_new_full_snapshot() -> None:
    state = GateMarketState("BTC_USDT")
    assert state.apply_book({**_full(), "_alina_transport": {"connection_id": "c1"}}) == EXPLOITABLE
    assert state.apply_book({**_delta(first=2, last=2), "_alina_transport": {"connection_id": "c2"}}) == DESYNC
    assert state.reason == "WS_RECONNECT_REQUIRES_SNAPSHOT"


def test_bug085_gate_contract_size_currency_must_match_the_base() -> None:
    ok, reason = validate_gate_contract(_contract(base_currency="ETH", contract_size="1"))
    assert not ok
    assert reason == "CONTRACT_BASE_MISMATCH"


def test_bug086_gate_spot_homonym_is_not_admitted_as_perpetual() -> None:
    assert parse_gate_contracts({"data": [_contract(type="spot"), _contract()]}) == [("BTC", "BTC_USDT")]


def test_bug087_gate_crossed_book_stays_unmeasurable_even_with_fresh_tick() -> None:
    state = GateMarketState("BTC_USDT")
    assert state.apply_book(_full(b=[["102", "1"]], a=[["101", "1"]])) == UNMEASURABLE
    assert state.reason == "INVALID_BBO"


def test_bug088_gate_depth_is_bounded_before_snapshot_exposure() -> None:
    bids = [[str(1000 - i), "1"] for i in range(gate.MAX_BOOK_LEVELS + 25)]
    asks = [[str(1300 + i), "1"] for i in range(gate.MAX_BOOK_LEVELS + 25)]
    state = GateMarketState("BTC_USDT")
    assert state.apply_book(_full(bids=bids, asks=asks)) == EXPLOITABLE
    assert len(state.bids) == gate.MAX_BOOK_LEVELS
    assert len(state.asks) == gate.MAX_BOOK_LEVELS


def test_bug089_gate_funding_rate_without_settlement_time_is_not_admitted() -> None:
    state = GateMarketState("BTC_USDT")
    state.apply_ticker({"funding_rate": "0.001"})
    assert state.funding_rate is None
    assert state.funding_ts_ms is None


def test_bug090_gate_exchange_timestamp_regression_invalidates_book() -> None:
    state = GateMarketState("BTC_USDT")
    assert state.apply_book(_full(timestamp_key="time_ms", timestamp=1_700_000_000_000)) == EXPLOITABLE
    assert state.apply_book(_delta(first=2, last=2, timestamp=1_700_000_001, time_ms=1_699_999_999_000)) == DESYNC
    assert state.reason == "EXCHANGE_TIMESTAMP_REGRESSION"


def test_bug090_bitget_exchange_timestamp_regression_is_fail_closed() -> None:
    state = BitgetMarketState("BTCUSDT")
    first = {"arg": {"channel": "books5", "instId": "BTCUSDT"}, "data": [{"ts": "1700000000000", "seq": "1", "bids": [["100", "1"]], "asks": [["101", "1"]]}]}
    second = {"arg": {"channel": "books5", "instId": "BTCUSDT"}, "data": [{"ts": "1699999999000", "seq": "2", "bids": [["100", "1"]], "asks": [["101", "1"]]}]}
    assert state.apply(first, receive_ts_ms=1_700_000_000_001) == EXPLOITABLE
    assert state.apply(second, receive_ts_ms=1_700_000_000_002) == DESYNC
    assert state.reason == "EXCHANGE_TIMESTAMP_REGRESSION"
