"""
Tests du moteur de fills réaliste (orderbook réel + coûts + PnL marké).

100% pur, déterministe, sans réseau. READ-ONLY / PAPER-ONLY.
"""

from __future__ import annotations

import pytest

from hyper_smart_observer.dydx_v4.paper_fill import (
    FILL_MODE_MARK,
    FILL_MODE_ORDERBOOK,
    compute_entry_fill,
    fee_usdc,
    funding_cost_usdc,
    orderbook_vwap,
    realized_pnl_usdc,
    round_trip_cost_bps,
    simple_mark_fill,
    unrealized_pnl_usdc,
)


# --------------------------------------------------------------------------- #
# VWAP carnet réel
# --------------------------------------------------------------------------- #
def test_orderbook_vwap_single_level():
    vwap, filled, slip = orderbook_vwap("BUY", 100.0, [(100.0, 1.0)])
    assert vwap == pytest.approx(100.0)
    assert filled == pytest.approx(100.0)
    assert slip == pytest.approx(0.0)


def test_orderbook_vwap_walks_levels_with_slippage():
    vwap, filled, slip = orderbook_vwap("BUY", 250.0, [(100.0, 1.0), (101.0, 5.0)])
    assert 100.0 < vwap < 101.0      # prix moyen entre les niveaux
    assert slip > 0                  # slippage réel dû à la profondeur
    assert filled == pytest.approx(250.0)


def test_orderbook_vwap_empty_or_zero():
    assert orderbook_vwap("BUY", 0.0, [(100.0, 1.0)]) is None
    assert orderbook_vwap("BUY", 100.0, []) is None


# --------------------------------------------------------------------------- #
# Fill mark simple
# --------------------------------------------------------------------------- #
def test_simple_mark_fill_adverse():
    assert simple_mark_fill("BUY", 100.0, 4.0, 6.0) == pytest.approx(100.08)   # +0,08%
    assert simple_mark_fill("SELL", 100.0, 4.0, 6.0) == pytest.approx(99.92)   # -0,08%


def test_compute_entry_fill_modes():
    ob = compute_entry_fill(FILL_MODE_ORDERBOOK, "BUY", 100.0, 100.0,
                            book=[(100.0, 1.0), (101.0, 5.0)], spread_bps=3, slippage_bps=5)
    assert ob.mode == FILL_MODE_ORDERBOOK and 100.0 <= ob.price <= 101.0
    mk = compute_entry_fill(FILL_MODE_ORDERBOOK, "BUY", 100.0, 100.0, book=None,
                            spread_bps=4, slippage_bps=6)
    assert mk.mode == FILL_MODE_MARK and mk.price == pytest.approx(100.08)


# --------------------------------------------------------------------------- #
# Coûts
# --------------------------------------------------------------------------- #
def test_fee_and_round_trip():
    assert fee_usdc(10_000.0, 5.0) == pytest.approx(5.0)
    assert round_trip_cost_bps(5, 3, 5, 2) == pytest.approx(20.0)


def test_funding_cost():
    assert funding_cost_usdc(10_000.0, 0.0001, 5.0) == pytest.approx(5.0)
    assert funding_cost_usdc(10_000.0, 0.0001, 0.0) == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# PnL marké aux vrais prix (reflète le mainnet)
# --------------------------------------------------------------------------- #
def test_realized_pnl_long_and_short():
    assert realized_pnl_usdc("LONG", 100, 110, 1, 1.0) == pytest.approx(9.0)
    assert realized_pnl_usdc("SHORT", 100, 90, 1, 1.0) == pytest.approx(9.0)


def test_realized_pnl_long_loss_with_funding():
    pnl = realized_pnl_usdc("LONG", 100, 95, 2, total_fees_usdc=1.0, funding_usdc=0.5)
    assert pnl == pytest.approx(-11.5)   # (-5*2) - 1 - 0.5


def test_unrealized_pnl_marks_to_real_price():
    assert unrealized_pnl_usdc("LONG", 100, 105, 2) == pytest.approx(10.0)
    assert unrealized_pnl_usdc("SHORT", 100, 105, 2) == pytest.approx(-10.0)
