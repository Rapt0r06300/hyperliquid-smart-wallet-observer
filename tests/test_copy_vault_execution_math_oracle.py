from __future__ import annotations

from decimal import Decimal, localcontext

import pytest

import hl_observer.backtesting.copy_vault_execution_math as execution_math
from hl_observer.backtesting.copy_vault_executable import execute_metaorder
from hl_observer.backtesting.copy_vault_execution_math import (
    _book_side,
    _walk_base_quantity,
    _walk_quote_notional,
)
from hl_observer.economics.assumptions import EconomicRunMode


@pytest.mark.parametrize(
    ("levels", "target"),
    [
        ([(1.0, 5e-10)], 1e-9),
        ([(1.0, 5e-11)], 1e-10),
        ([], 5e-324),
    ],
)
def test_observed_depth_shortfall_is_never_converted_into_a_fill(levels, target):
    quote_result = _walk_quote_notional(levels, target)
    base_result = _walk_base_quantity(levels, target)

    assert quote_result is None
    assert base_result is None


@pytest.mark.parametrize("target", [0.0, -1.0, float("nan"), float("inf"), True])
def test_invalid_quote_target_fails_closed(target):
    assert _walk_quote_notional([(100.0, 1.0)], target) is None


@pytest.mark.parametrize("target", [0.0, -1.0, float("nan"), float("inf"), True])
def test_invalid_base_target_fails_closed(target):
    assert _walk_base_quantity([(100.0, 1.0)], target) is None


def test_quote_walk_rejects_a_realistic_notional_shortfall_beyond_float_ulp():
    available_quote = 150.0 - 5e-9

    assert _walk_quote_notional([(100.0, available_quote / 100.0)], 150.0) is None


def test_base_walk_rejects_a_small_realistic_quantity_shortfall():
    assert _walk_base_quantity([(100.0, 1.5 - 5e-11)], 1.5) is None


@pytest.mark.parametrize(
    ("raw_level", "expected_best"),
    [
        ([100.0, True], 100.0),
        ([True, 1.0], 1.0),
    ],
)
def test_book_side_rejects_booleans_before_numeric_coercion(raw_level, expected_best):
    assert _book_side(
        {"asks5": [raw_level]},
        "asks5",
        expected_best=expected_best,
        descending=False,
    ) is None


def test_book_side_requires_exact_match_between_top_and_l2_best_level():
    assert _book_side(
        {"asks5": [[100.00000005, 1.0]]},
        "asks5",
        expected_best=100.0,
        descending=False,
    ) is None


def test_multilevel_quote_and_base_walk_match_independent_decimal_oracle():
    with localcontext() as ctx:
        ctx.prec = 80
        quote_target = Decimal("150")
        asks = [(Decimal("100"), Decimal("1")), (Decimal("101"), Decimal("1"))]
        quote_quantity = Decimal("1") + Decimal("50") / Decimal("101")
        quote_vwap = quote_target / quote_quantity

        base_target = Decimal("1.25")
        bids = [(Decimal("101"), Decimal("0.5")), (Decimal("100"), Decimal("1"))]
        base_vwap = (Decimal("101") * Decimal("0.5") + Decimal("100") * Decimal("0.75")) / base_target

    actual_quote = _walk_quote_notional(
        [(float(price), float(size)) for price, size in asks], float(quote_target)
    )
    actual_base = _walk_base_quantity(
        [(float(price), float(size)) for price, size in bids], float(base_target)
    )

    assert actual_quote is not None
    assert actual_base is not None
    assert actual_quote[1] == pytest.approx(float(quote_quantity), rel=1e-14)
    assert actual_quote[0] == pytest.approx(float(quote_vwap), rel=1e-14)
    assert actual_base == pytest.approx(float(base_vwap), rel=1e-14)


@pytest.mark.parametrize(
    ("walk", "levels", "target"),
    [
        (_walk_quote_notional, [(100.0, 1.0), (101.0, 1.0)], 150.0),
        (_walk_base_quantity, [(101.0, 0.5), (100.0, 1.0)], 1.25),
    ],
)
def test_comfortably_liquid_walk_uses_bounded_fast_path(
    monkeypatch, walk, levels, target
):
    def decimal_fallback_must_not_run(_levels):
        pytest.fail("wide-margin replay walk unexpectedly used Decimal fallback")

    monkeypatch.setattr(execution_math, "_decimal_levels", decimal_fallback_must_not_run)

    assert walk(levels, target) is not None


def test_depth_within_one_float_ulp_uses_decimal_boundary_check():
    import math

    quote_target = math.nextafter(0.1 * 0.3, math.inf)
    base_target = math.nextafter(0.3, math.inf)

    assert _walk_quote_notional([(0.1, 0.3)], quote_target) is None
    assert _walk_base_quantity([(1.0, 0.3)], base_target) is None


@pytest.mark.parametrize(
    ("walk", "levels", "target"),
    [
        (_walk_quote_notional, [(100.0, 1.0), (200.0, 1.0)], 100.0),
        (_walk_base_quantity, [(100.0, 0.5), (200.0, 1.0)], 0.5),
    ],
)
def test_level_boundary_uses_decimal_oracle(monkeypatch, walk, levels, target):
    original = execution_math._decimal_levels
    calls = 0

    def track_decimal_fallback(book_levels):
        nonlocal calls
        calls += 1
        return original(book_levels)

    monkeypatch.setattr(execution_math, "_decimal_levels", track_decimal_fallback)

    assert walk(levels, target) is not None
    assert calls == 1


def test_multilevel_quote_capacity_one_ulp_edges_fail_closed():
    import math

    levels = [(0.1, 0.1), (0.3, 0.2), (10.01, 0.0001)]
    with localcontext() as ctx:
        ctx.prec = 80
        capacity = sum(
            (Decimal(str(price)) * Decimal(str(size)) for price, size in levels),
            Decimal(0),
        )
    rounded_capacity = float(capacity)

    just_sufficient = math.nextafter(rounded_capacity, 0.0)
    just_insufficient = math.nextafter(rounded_capacity, math.inf)

    assert Decimal(str(just_sufficient)) < capacity
    assert Decimal(str(just_insufficient)) > capacity
    assert _walk_quote_notional(levels, just_sufficient) is not None
    assert _walk_quote_notional(levels, just_insufficient) is None


def test_multilevel_base_capacity_one_ulp_edges_fail_closed():
    import math

    levels = [(0.1, 0.1), (0.3, 0.2), (10.01, 0.0001)]
    with localcontext() as ctx:
        ctx.prec = 80
        capacity = sum((Decimal(str(size)) for _, size in levels), Decimal(0))
    rounded_capacity = float(capacity)

    just_sufficient = math.nextafter(rounded_capacity, 0.0)
    just_insufficient = math.nextafter(rounded_capacity, math.inf)

    assert Decimal(str(just_sufficient)) < capacity
    assert Decimal(str(just_insufficient)) > capacity
    assert _walk_base_quantity(levels, just_sufficient) is not None
    assert _walk_base_quantity(levels, just_insufficient) is None


def test_prepared_float_cache_does_not_accept_bool_by_numeric_key_collision():
    valid = [(100.0, 1.0)]
    invalid_quantity = [(100.0, True)]
    invalid_price = [(True, 1.0)]

    assert _walk_quote_notional(valid, 50.0) is not None
    assert _walk_quote_notional(invalid_quantity, 50.0) is None
    assert _walk_quote_notional(invalid_price, 50.0) is None


def test_subnormal_sufficient_depth_returns_positive_finite_values():
    target = float.fromhex("0x0.0000000000001p-1022")

    quote_result = _walk_quote_notional([(1.0, target)], target)
    base_result = _walk_base_quantity([(1.0, target)], target)

    assert quote_result == (1.0, target)
    assert base_result == 1.0


def test_copy_vault_trade_costs_match_decimal_replay_oracle():
    metaorder = {
        "metaorder_id": "decimal-oracle-metaorder",
        "vault": "0xoracle",
        "coin": "BTC",
        "signal_ts_ms": 1_000,
        "direction": 1,
        "first_fill_ts_ms": 1_000,
    }

    def book(
        ts_ms: int,
        *,
        bid: float,
        ask: float,
        bids: list[list[float]],
        asks: list[list[float]],
        source_line: int,
    ) -> dict:
        return {
            "coin": "BTC",
            "ts_ms": ts_ms,
            "bid": bid,
            "ask": ask,
            "capacity_usd": 1_000.0,
            "bids5": bids,
            "asks5": asks,
            "source_line": source_line,
            "causal_observation": False,
        }

    reference = book(
        1_000,
        bid=99.0,
        ask=100.0,
        bids=[[99.0, 2.0]],
        asks=[[100.0, 2.0]],
        source_line=1,
    )
    entry = book(
        2_000,
        bid=99.0,
        ask=100.0,
        bids=[[99.0, 2.0]],
        asks=[[100.0, 1.0], [101.0, 1.0]],
        source_line=2,
    )
    exit_book = book(
        302_000,
        bid=101.0,
        ask=102.0,
        bids=[[101.0, 0.5], [100.0, 2.0]],
        asks=[[102.0, 2.0]],
        source_line=3,
    )

    with localcontext() as ctx:
        ctx.prec = 80
        requested_quote = Decimal("150")
        entry_quantity = Decimal("1") + Decimal("50") / Decimal("101")
        entry_vwap = requested_quote / entry_quantity
        exit_quote = Decimal("101") * Decimal("0.5") + Decimal("100") * (
            entry_quantity - Decimal("0.5")
        )
        exit_vwap = exit_quote / entry_quantity
        fees = (requested_quote + exit_quote) * Decimal("4.5") / Decimal("10000")
        expected_net = exit_quote - requested_quote - fees

    trade, reason = execute_metaorder(
        metaorder,
        [reference, entry, exit_book],
        horizon_ms=300_000,
        copy_delay_ms=1_000,
        notional_usd=150.0,
        fee_bps=4.5,
        economic_mode=EconomicRunMode.EXPLORATORY,
    )

    assert reason == "LIQUIDATABLE_NET"
    assert trade is not None
    assert trade["quantity"] == pytest.approx(float(entry_quantity), rel=1e-14)
    assert trade["entry_price"] == pytest.approx(float(entry_vwap), rel=1e-14)
    assert trade["exit_price"] == pytest.approx(float(exit_vwap), rel=1e-14)
    assert trade["fees_usd"] == pytest.approx(float(fees), rel=1e-13, abs=1e-13)
    assert trade["net_pnl_usd"] == pytest.approx(float(expected_net), rel=1e-12, abs=1e-12)
