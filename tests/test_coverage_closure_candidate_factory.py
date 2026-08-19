from __future__ import annotations

import pytest

import hl_observer.loops.candidate_factory as factory
from hl_observer.mainnet_readonly_observer.observer import MainnetObservation


def test_fill_and_delta_helpers() -> None:
    obs = MainnetObservation(source="s", all_mids={"BTC": 100.0})
    parsed = factory._parse_fill(
        "w",
        {"coin": "btc", "dir": "Open Long", "px": "101", "time": 1000},
        obs,
        999999,
    )
    assert parsed == ("Open Long", "open", "long", "BTC", 101.0, 1_000_000)
    assert factory._parse_fill("w", {"dir": "Open Long"}, obs, 1).reason == "missing_coin"
    assert factory._map_fill_direction("Open Long", {"startPosition": "2"}) == ("add", "long")
    assert factory._map_fill_direction("Close Long", {"startPosition": "2", "sz": "2"}) == ("close", "long")
    assert factory._map_delta_action("OPEN_SHORT", {}) == ("open", "short")
    assert factory._map_delta_action("FLIP", {}) == (None, None)
    assert factory._map_delta_action("ADD", {"side": "LONG"}) == ("add", "long")
    delta = {"coin": "btc", "action": "OPEN_LONG", "price": 100, "detected_at_ms": 123}
    assert factory._parse_position_delta(delta, {}, 999) == (
        "open", "long", "BTC", 100.0, 123_000, "OPEN_LONG"
    )


def test_orderbook_cost_helpers() -> None:
    assert factory._book_metrics({}) == (5.0, 0.0)
    book = {
        "levels": [
            [{"px": "99", "sz": "2"}, [98, 1]],
            [{"price": "101", "size": "3"}, [102, 2]],
        ]
    }
    spread, depth = factory._book_metrics(book)
    assert spread == pytest.approx(200.0)
    assert depth == pytest.approx(99 * 2 + 98 + 101 * 3 + 102 * 2)
    assert factory._estimate_slippage_bps(depth_usdc=0, min_depth_usdc=100) == 12.0
    assert factory._estimate_slippage_bps(depth_usdc=1000, min_depth_usdc=100) == 1.5
    assert factory._estimate_slippage_bps(depth_usdc=100, min_depth_usdc=100) == 4.0
    assert factory._estimate_slippage_bps(depth_usdc=99, min_depth_usdc=100) == 10.0


def test_build_candidates_from_observation_and_deltas(monkeypatch) -> None:
    monkeypatch.setattr(factory, "unix_ms", lambda: 2_000_000)
    observation = MainnetObservation(
        source="ro",
        observed_at_ms=1_900_000,
        all_mids={"BTC": 100.0},
        l2_books={"BTC": {"levels": [[[99, 100]], [[101, 100]]]}},
        wallet_fills={
            "w1": [
                {"coin": "BTC", "dir": "Open Long", "px": 100, "time": 1999, "hash": "h1"},
                {"coin": "", "dir": "Open Long", "px": 1},
            ]
        },
    )
    report = factory.build_signal_candidates_from_observation(observation, max_candidates=1)
    assert len(report.candidates) == 1
    assert report.candidates[0].id.startswith("ro-")
    assert report.candidates[0].estimated_fee_bps == 4.0
    assert report.skipped[0].reason == "max_candidates_reached"

    deltas = [
        {"wallet_address": "w1", "coin": "BTC", "action": "OPEN_LONG", "price": 100, "detected_at_ms": 1_999_000},
        {"coin": "ETH", "action": "CLOSE_SHORT", "price": 200, "detected_at_ms": 1_998_000},
        {"wallet": "w3", "coin": "SOL", "action": "FLIP", "price": 50},
    ]
    delta_report = factory.build_signal_candidates_from_position_deltas(deltas, max_candidates=5)
    assert len(delta_report.candidates) == 2
    assert delta_report.candidates[1].source_wallet == "UNKNOWN_WALLET"
    assert [item.reason for item in delta_report.skipped] == ["unknown_delta"]
