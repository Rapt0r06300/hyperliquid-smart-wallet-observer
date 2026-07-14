"""Tests des algorithmes de microstructure (données synthétiques)."""
from __future__ import annotations

from hl_observer.backtesting.microstructure import (
    kyle_lambda,
    lee_ready_sign,
    order_flow_imbalance,
    slippage_from_depth,
    vpin,
)


def test_ofi_positive_on_buy_pressure():
    # taille au bid qui GONFLE (pression acheteuse), ask stable -> OFI > 0
    bid_p = [100.0] * 5
    bid_s = [10.0, 20.0, 30.0, 40.0, 50.0]
    ask_p = [101.0] * 5
    ask_s = [10.0] * 5
    assert order_flow_imbalance(bid_p, bid_s, ask_p, ask_s) > 0


def test_kyle_lambda_recovers_impact():
    vols = [float(v) for v in range(-20, 21)]
    dprice = [0.5 * v for v in vols]                 # impact = 0.5 par unité
    assert abs(kyle_lambda(dprice, vols) - 0.5) < 1e-6


def test_vpin_bounds():
    assert vpin([10, 10, 10], [10, 10, 10]) < 0.01   # flux équilibré -> ~0
    assert vpin([10, 10, 10], [0, 0, 0]) > 0.99      # tout acheteur -> ~1


def test_lee_ready():
    assert lee_ready_sign(100.6, 100.5) == 1
    assert lee_ready_sign(100.4, 100.5) == -1
    assert lee_ready_sign(100.5, 100.5, prev_trade=100.4) == 1


def test_slippage_walks_the_book():
    levels = [(100.0, 5.0), (100.5, 5.0), (101.0, 5.0)]
    assert slippage_from_depth(2.0, levels, side="BUY") == 0.0   # rempli au top -> 0 slippage
    assert slippage_from_depth(12.0, levels, side="BUY") > 0.0   # doit walker plus profond
