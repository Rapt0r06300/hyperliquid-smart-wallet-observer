"""Tests des modèles d'exécution / microstructure."""
from __future__ import annotations

from hl_observer.backtesting.execution_models import (
    almgren_chriss_cost,
    effective_spread,
    micro_price,
    twap_schedule,
)


def test_micro_price_leans_to_pressure():
    mid = 100.5
    mp = micro_price(100.0, 101.0, bid_size=10.0, ask_size=1.0)   # grosse pression acheteuse
    assert mp > mid                                                # tire vers l'ask


def test_effective_spread_positive_when_paying_up():
    assert effective_spread(100.6, 100.5, "BUY") > 0
    assert effective_spread(100.4, 100.5, "SELL") > 0


def test_almgren_cost_grows_with_size():
    small = almgren_chriss_cost(10, adv=1000, spread_bps=4)
    big = almgren_chriss_cost(500, adv=1000, spread_bps=4)
    assert big > small


def test_twap_even_slices():
    s = twap_schedule(100.0, 4)
    assert len(s) == 4 and abs(sum(s) - 100.0) < 1e-9 and all(abs(q - 25.0) < 1e-9 for q in s)
