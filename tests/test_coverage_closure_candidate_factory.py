from __future__ import annotations

from types import SimpleNamespace

import pytest

import hl_observer.loops.candidate_factory as factory
from hl_observer.mainnet_readonly_observer.observer import MainnetObservation


def test_skip_and_report_to_dict() -> None:
    skip = factory.CandidateFactorySkip(wallet="w", reason="r", raw={"x": 1})
    assert skip.to_dict() == {"wallet": "w", "reason": "r", "raw": {"x": 1}}
    report = factory.CandidateFactoryReport(
        source="s", generated_at_ms=1, observed_at_ms=2,
        candidates=[], skipped=[skip], methodology="m",
    )
    assert report.to_dict() == {
        "source":"s", "generated_at_ms":1, "observed_at_ms":2,
        "candidate_count":0, "candidates":[], "skipped":[skip.to_dict()], "methodology":"m",
    }


def test_fill_parsing_directions_prices_and_timestamps() -> None:
    obs = MainnetObservation(source="s", all_mids={"BTC": 100.0})
    parsed = factory._parse_fill("w", {"coin":"btc","dir":"Open Long","px":"101","time": 1000}, obs, 999999)
    assert parsed == ("Open Long", "open", "long", "BTC", 101.0, 1_000_000)
    assert factory._parse_fill("w", {"dir":"Open Long"}, obs, 1).reason == "missing_coin"
    assert factory._parse_fill("w", {"coin":"BTC","dir":"weird"}, obs, 1).reason == "unsupported_fill_direction"
    parsed = factory._parse_fill("w", {"coin":"BTC","dir":"Open Short","px":0}, obs, 123)
    assert parsed[4] == 100.0
    assert factory._parse_fill("w", {"coin":"ETH","dir":"Open Long","px":0}, obs, 1).reason == "missing_price"
    assert factory._map_fill_direction("Open Long", {"startPosition": "2"}) == ("add", "long")
    assert factory._map_fill_direction("Open Short", {"startPosition": "-2"}) == ("add", "short")
    assert factory._map_fill_direction("Close Long", {"startPosition":"2","sz":"2"}) == ("close", "long")
    assert factory._map_fill_direction("Close Long", {"startPosition":"2","sz":"1"}) == ("reduce", "long")
    assert factory._map_fill_direction("Close Short", {"startPosition":"-2","sz":"2"}) == ("close", "short")
    assert factory._map_fill_direction("bad", {}) == (None, None)
    assert factory._is_full_close({"startPosition":2,"sz":2})
    assert not factory._is_full_close({"startPosition":2,"sz":1})
    assert factory._timestamp_ms({"timestamp": 1_700_000_000_000}, 5) == 1_700_000_000_000
    assert factory._timestamp_ms({}, 5) == 5


def test_position_delta_mapping_inference_raw_and_values() -> None:
    assert factory._map_delta_action("OPEN_LONG", {}) == ("open","long")
    assert factory._map_delta_action("OPEN_SHORT", {}) == ("open","short")
    assert factory._map_delta_action("CLOSE_LONG", {}) == ("close","long")
    assert factory._map_delta_action("CLOSE_SHORT", {}) == ("close","short")
    assert factory._map_delta_action("FLIP", {}) == (None,None)
    assert factory._map_delta_action("ADD", {"side":"LONG"}) == ("add","long")
    assert factory._map_delta_action("INCREASE", {"new_size":-1}) == ("add","short")
    assert factory._map_delta_action("REDUCE", {"current_size":1}) == ("reduce","long")
    assert factory._map_delta_action("CLOSE", {"direction":"SHORT"}) == ("close","short")
    assert factory._map_delta_action("OPEN", {"position_side":"LONG"}) == ("open","long")
    assert factory._map_delta_action("OTHER", {}) == (None,None)
    assert factory._infer_delta_side({"new_side":"my long"}) == "long"
    assert factory._infer_delta_side({"new_signed_size":-2}) == "short"
    assert factory._infer_delta_side({"new_size":0}) is None

    delta = {"coin":"btc","action":"OPEN_LONG","price":100,"detected_at_ms":123}
    assert factory._parse_position_delta(delta, {}, 999) == ("open","long","BTC",100.0,123000,"OPEN_LONG")
    assert factory._parse_position_delta({"action":"OPEN_LONG"}, {}, 1).reason == "missing_coin"
    assert factory._parse_position_delta({"coin":"BTC","action":"FLIP"}, {}, 1).reason == "unknown_delta"
    parsed = factory._parse_position_delta({"coin":"BTC","action":"OPEN_LONG","price":0}, {"BTC":101}, 1)
    assert parsed[3] == 101.0
    assert factory._parse_position_delta({"coin":"BTC","action":"OPEN_LONG"}, {}, 1).reason == "missing_price"

    obj = SimpleNamespace(wallet_address="w", coin="BTC", action="OPEN_LONG", raw_json={"x":1,"coin":"ETH"})
    raw = factory._raw_delta(obj)
    assert raw["wallet_address"] == "w" and raw["coin"] == "BTC" and raw["x"] == 1
    assert factory._raw_delta({"a":1}) == {"a":1}
    assert factory._delta_value({"raw_json":{"x":2}}, "x") == 2
    assert factory._delta_value(obj, "wallet_address") == "w"
    assert factory._delta_value(SimpleNamespace(raw_json={"x":3}), "x") == 3
    assert factory._delta_value({}, "missing") is None
    assert factory._delta_timestamp_ms({"time":123}, 9) == 123000
    assert factory._delta_timestamp_ms({}, 9) == 9


def test_book_level_depth_slippage_and_float_helpers() -> None:
    assert factory._book_metrics({}) == (5.0,0.0)
    book = {"levels":[
        [{"px":"99","sz":"2"}, [98,1]],
        [{"price":"101","size":"3"}, [102,2]],
    ]}
    spread, depth = factory._book_metrics(book)
    assert spread == pytest.approx(200.0)
    assert depth == pytest.approx(99*2 + 98 + 101*3 + 102*2)
    bad = {"levels":[[[0,1]], [[101,1]]]}
    assert factory._book_metrics(bad)[0] == 5.0
    assert factory._levels_depth([[10,2], {"px":5,"sz":3}, ["bad",1]]) == 35.0
    assert factory._level_price({"price":"1.5"}) == 1.5
    assert factory._level_price([2,3]) == 2.0
    assert factory._level_price("bad") is None
    assert factory._level_size({"size":"4"}) == 4.0
    assert factory._level_size([2,3]) == 3.0
    assert factory._level_size([2]) is None
    assert factory._estimate_slippage_bps(depth_usdc=0, min_depth_usdc=100) == 12.0
    assert factory._estimate_slippage_bps(depth_usdc=1000, min_depth_usdc=100) == 1.5
    assert factory._estimate_slippage_bps(depth_usdc=100, min_depth_usdc=100) == 4.0
    assert factory._estimate_slippage_bps(depth_usdc=99, min_depth_usdc=100) == 10.0
    assert factory._float_or_none(None) is None
    assert factory._float_or_none("1.2") == 1.2
    assert factory._float_or_none("x") is None


def test_build_from_observation_generates_skips_costs_and_max(monkeypatch) -> None:
    monkeypatch.setattr(factory, "unix_ms", lambda: 2_000_000)
    obs = MainnetObservation(
        source="ro", observed_at_ms=1_900_000,
        all_mids={"BTC":100.0,"ETH":200.0},
        l2_books={"BTC":{"levels":[[[99,100]],[[101,100]]]}},
        wallet_fills={
            "w1":[
                {"coin":"BTC","dir":"Open Long","px":100,"time":1999,"hash":"h1"},
                {"coin":"","dir":"Open Long","px":1},
                {"coin":"ETH","dir":"Open Short","px":200,"time":1998,"hash":"h2"},
            ]
        },
    )
    report = factory.build_signal_candidates_from_observation(obs, max_candidates=1)
    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.id.startswith("ro-") and candidate.coin == "BTC" and candidate.side == "long"
    assert candidate.signal_type == "open"
    assert candidate.estimated_fee_bps == 4.0
    assert candidate.orderbook_depth_usdc > 5000
    reasons = [s.reason for s in report.skipped]
    assert reasons == ["max_candidates_reached", "max_candidates_reached"]
    dumped = report.to_dict()
    assert dumped["candidate_count"] == 1 and dumped["source"] == "ro"


def test_build_from_position_deltas_generates_skips_close_and_default_wallet(monkeypatch) -> None:
    monkeypatch.setattr(factory, "unix_ms", lambda: 2_000_000)
    deltas = [
        {"wallet_address":"w1","coin":"BTC","action":"OPEN_LONG","price":100,"detected_at_ms":1_999_000},
        {"coin":"ETH","action":"CLOSE_SHORT","price":200,"detected_at_ms":1_998_000},
        {"wallet":"w3","coin":"SOL","action":"FLIP","price":50},
    ]
    report = factory.build_signal_candidates_from_position_deltas(
        deltas, all_mids={}, l2_books={}, observed_at_ms=1_900_000, max_candidates=5
    )
    assert len(report.candidates) == 2
    assert report.candidates[0].id.startswith("pd-")
    assert report.candidates[1].source_wallet == "UNKNOWN_WALLET"
    assert report.candidates[1].signal_type == "close"
    assert [s.reason for s in report.skipped] == ["unknown_delta"]

    limited = factory.build_signal_candidates_from_position_deltas(deltas, max_candidates=1)
    assert len(limited.candidates) == 1
    assert sum(s.reason == "max_candidates_reached" for s in limited.skipped) == 2
