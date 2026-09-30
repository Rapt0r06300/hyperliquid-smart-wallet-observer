from __future__ import annotations

import pytest

from hl_observer.arbitrage.cross_venue_contract import (
    BUY_HL_SELL_BINANCE,
    SELL_HL_BUY_BINANCE,
    VenueAction,
    direction_from_hyperliquid_sens,
    executable_price,
    select_executable_direction,
)


def test_select_buy_hl_sell_binance_from_executable_prices() -> None:
    direction, gap, components = select_executable_direction(
        hl_bid=99.9,
        hl_ask=100.0,
        binance_bid=101.0,
        binance_ask=101.1,
    )
    assert direction == BUY_HL_SELL_BINANCE
    assert direction.hyperliquid_sens == 1
    assert gap == components["buy_hl_sell_binance_bps"]
    assert executable_price(direction.hyperliquid, bid=99.9, ask=100.0) == 100.0
    assert executable_price(direction.binance, bid=101.0, ask=101.1) == 101.0


def test_select_sell_hl_buy_binance_from_executable_prices() -> None:
    direction, gap, components = select_executable_direction(
        hl_bid=101.0,
        hl_ask=101.1,
        binance_bid=99.9,
        binance_ask=100.0,
    )
    assert direction == SELL_HL_BUY_BINANCE
    assert direction.hyperliquid_sens == -1
    assert gap == components["sell_hl_buy_binance_bps"]
    assert executable_price(direction.hyperliquid, bid=101.0, ask=101.1) == 101.0
    assert executable_price(direction.binance, bid=99.9, ask=100.0) == 100.0


@pytest.mark.parametrize(
    ("sens", "expected"),
    [(1, BUY_HL_SELL_BINANCE), (-1, SELL_HL_BUY_BINANCE)],
)
def test_legacy_sens_conversion_is_exact(sens: int, expected: object) -> None:
    assert direction_from_hyperliquid_sens(sens) == expected


def test_invalid_direction_and_crossed_books_are_rejected() -> None:
    with pytest.raises(ValueError):
        direction_from_hyperliquid_sens(0)
    with pytest.raises(ValueError, match="crossed local book"):
        select_executable_direction(
            hl_bid=101.0,
            hl_ask=100.0,
            binance_bid=99.0,
            binance_ask=100.0,
        )
    assert VenueAction.BUY.value == "BUY"
