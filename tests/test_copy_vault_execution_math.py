from __future__ import annotations

from decimal import Decimal, localcontext

import pytest

from hl_observer.backtesting.copy_vault_execution_math import (
    _walk_base_quantity,
    _walk_quote_notional,
)


def _decimal_quote_walk(levels, target_quote: float) -> tuple[Decimal, Decimal] | None:
    with localcontext() as context:
        context.prec = 50
        remaining = Decimal(str(target_quote))
        quantity = Decimal(0)
        for price_raw, quantity_raw in levels:
            price, available = Decimal(str(price_raw)), Decimal(str(quantity_raw))
            taken = min(remaining, price * available)
            quantity += taken / price
            remaining -= taken
            if remaining <= 0:
                break
        if remaining > 0 or quantity <= 0:
            return None
        return Decimal(str(target_quote)) / quantity, quantity


def _decimal_base_walk(levels, target_quantity: float) -> Decimal | None:
    with localcontext() as context:
        context.prec = 50
        remaining = Decimal(str(target_quantity))
        notional = Decimal(0)
        for price_raw, quantity_raw in levels:
            price, available = Decimal(str(price_raw)), Decimal(str(quantity_raw))
            taken = min(remaining, available)
            notional += price * taken
            remaining -= taken
            if remaining <= 0:
                break
        if remaining > 0:
            return None
        return notional / Decimal(str(target_quantity))


@pytest.mark.parametrize(
    "levels,target",
    [
        ([(100.0, 5e-12)], 1e-9),
        ([(100.0, 5e-12), (101.0, 1e-12)], 1e-9),
    ],
)
def test_quote_walk_does_not_turn_missing_depth_into_a_fill(levels, target) -> None:
    assert _decimal_quote_walk(levels, target) is None
    assert _walk_quote_notional(levels, target) is None


@pytest.mark.parametrize(
    "levels,target",
    [
        ([(100_000.0, 5e-11)], 1e-10),
        ([(100_000.0, 4e-11), (101_000.0, 1e-11)], 1e-10),
    ],
)
def test_base_walk_does_not_accept_materially_unfilled_quantity(levels, target) -> None:
    assert _decimal_base_walk(levels, target) is None
    assert _walk_base_quantity(levels, target) is None


def test_base_walk_never_returns_a_fill_without_any_visible_depth() -> None:
    assert _walk_base_quantity([], 5e-324) is None


def test_base_walk_rejects_unrepresentable_quote_notional() -> None:
    # Finite price and size can still overflow their product in binary float.
    # An infinite VWAP must never enter a paper fill or PnL ledger.
    assert _walk_base_quantity([(1e308, 1e308)], 1e308) is None


@pytest.mark.parametrize(
    "levels,target",
    [
        ([(100.0, 0.1), (100.0, 0.2)], 0.3),
        ([(99.5, 0.2), (100.0, 0.5)], 0.4),
    ],
)
def test_quote_walk_matches_decimal_oracle_when_depth_is_sufficient(levels, target) -> None:
    expected = _decimal_quote_walk(levels, target)

    actual = _walk_quote_notional(levels, target)

    assert expected is not None and actual is not None
    expected_price, expected_quantity = expected
    assert float(expected_price) == pytest.approx(actual[0], rel=1e-14, abs=1e-14)
    assert float(expected_quantity) == pytest.approx(actual[1], rel=1e-14, abs=1e-14)


@pytest.mark.parametrize(
    "levels,target",
    [
        ([(100.0, 0.1), (100.0, 0.2)], 0.3),
        ([(99.5, 0.2), (100.0, 0.5)], 0.4),
    ],
)
def test_base_walk_matches_decimal_oracle_when_depth_is_sufficient(levels, target) -> None:
    expected = _decimal_base_walk(levels, target)

    actual = _walk_base_quantity(levels, target)

    assert expected is not None and actual is not None
    assert float(expected) == pytest.approx(actual, rel=1e-14, abs=1e-14)
