"""Tests du stress-testing portefeuille."""
from __future__ import annotations

from hl_observer.backtesting.stress_testing import (
    monte_carlo_paths,
    portfolio_stress,
    regime_conditional_size,
)


def test_portfolio_stress_pnl():
    # 1000$ long BTC, choc -10% -> -100$ ; 500$ short ETH (-500 notional), choc +5% -> -25$
    pnl = portfolio_stress({"BTC": 1000.0, "ETH": -500.0}, {"BTC": -0.10, "ETH": 0.05})
    assert abs(pnl - (-125.0)) < 1e-9


def test_monte_carlo_distribution_ordering():
    r = monte_carlo_paths(mu=0.0, sigma=0.01, steps=100, n=500, seed=1)
    assert r["p5"] < r["median"] < r["p95"]
    assert 0.0 <= r["prob_loss"] <= 1.0


def test_regime_conditional_size_reduces_in_high_vol():
    assert regime_conditional_size(100.0, regime_vol=0.40, target_vol=0.10) == 25.0   # 4x vol -> 1/4
    assert regime_conditional_size(100.0, regime_vol=0.05, target_vol=0.10) == 100.0  # peu volatil -> plein
