from __future__ import annotations

import pytest

from hl_observer.paper_trading.exec_model import simulate_depth_execution
from hl_observer.simulation.orderbook_execution_simulator import (
    simulate_orderbook_execution,
)


def test_buy_walks_only_asks_and_records_exact_vwap_levels() -> None:
    result = simulate_depth_execution(
        side="BUY",
        notional_usdc=152.0,
        mid_price=100.0,
        asks=((101.0, 1.0), (102.0, 1.0)),
        bids=((1.0, 1_000_000.0),),
        min_fill_ratio=1.0,
    )

    assert result.reason == "FILLED"
    assert result.levels_consumed == 2
    assert result.filled_quantity == pytest.approx(1.5)
    assert result.average_fill_price == pytest.approx(152.0 / 1.5)
    assert tuple(level.price for level in result.level_fills) == (101.0, 102.0)
    assert result.level_fills[0].filled_quantity == 1.0
    assert result.level_fills[1].filled_quantity == 0.5
    assert sum(level.filled_notional_usdc for level in result.level_fills) == 152.0


def test_sell_walks_only_bids_in_descending_executable_order() -> None:
    result = simulate_depth_execution(
        side="SELL",
        notional_usdc=149.0,
        mid_price=100.0,
        asks=((1_000.0, 1_000.0),),
        bids=((99.0, 1.0), (100.0, 0.5)),
        min_fill_ratio=1.0,
    )

    assert result.reason == "FILLED"
    assert tuple(level.price for level in result.level_fills) == (100.0, 99.0)
    assert result.filled_quantity == pytest.approx(1.5)
    assert result.average_fill_price == pytest.approx(149.0 / 1.5)


def test_insufficient_depth_is_partial_never_invented_full_fill() -> None:
    result = simulate_depth_execution(
        side="BUY",
        notional_usdc=500.0,
        mid_price=100.0,
        asks=((101.0, 1.0),),
        bids=((99.0, 1_000.0),),
        min_fill_ratio=0.0,
    )

    assert result.partial is True
    assert result.missed is False
    assert result.reason == "PARTIAL_FILL"
    assert result.filled_notional_usdc == 101.0
    assert result.missed_notional_usdc == 399.0
    assert result.fill_ratio == pytest.approx(0.202)
    assert result.level_fills[0].filled_quantity == 1.0


def test_high_minimum_fill_ratio_marks_same_partial_as_missed() -> None:
    result = simulate_depth_execution(
        side="BUY",
        notional_usdc=500.0,
        mid_price=100.0,
        asks=((101.0, 1.0),),
        bids=((99.0, 1_000.0),),
        min_fill_ratio=0.8,
    )

    assert result.partial is True
    assert result.missed is True
    assert result.reason == "MISSED_FILL"
    assert result.filled_notional_usdc == 101.0


def test_legacy_orderbook_adapter_delegates_the_canonical_walk() -> None:
    direct = simulate_depth_execution(
        side="BUY",
        notional_usdc=152.0,
        mid_price=100.0,
        asks=((101.0, 1.0), (102.0, 1.0)),
        bids=((99.0, 1.0),),
        min_fill_ratio=1.0,
    )
    adapted = simulate_orderbook_execution(
        side="BUY",
        notional_usdc=152.0,
        mid_price=100.0,
        asks=((101.0, 1.0), (102.0, 1.0)),
        bids=((99.0, 1.0),),
        min_fill_ratio=1.0,
    )

    assert adapted.average_fill_price == direct.average_fill_price
    assert adapted.filled_notional_usdc == direct.filled_notional_usdc
    assert adapted.missed_notional_usdc == direct.missed_notional_usdc
    assert adapted.fill_ratio == direct.fill_ratio
    assert adapted.slippage_bps == direct.slippage_bps


def test_book_walk_keeps_legacy_dict_level_compatibility() -> None:
    result = simulate_depth_execution(
        side="BUY",
        notional_usdc=50.0,
        mid_price=100.0,
        asks=({"px": "100.1", "sz": "1.0"},),
        bids=({"price": "99.9", "size": "1.0"},),
        min_fill_ratio=0.0,
    )

    assert result.filled_notional_usdc == 50.0
    assert result.average_fill_price == 100.1
    assert result.level_fills[0].filled_quantity == pytest.approx(50.0 / 100.1)
