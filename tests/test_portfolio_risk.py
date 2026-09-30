"""Tests du risque portefeuille."""
from __future__ import annotations

from hl_observer.backtesting.portfolio_risk import (
    drawdown_stop_triggered,
    exposure_ok,
    risk_parity_weights,
    too_correlated,
)


def test_too_correlated():
    base = [1.0, 2.0, 3.0, 4.0, 5.0]
    same = [2.0, 4.0, 6.0, 8.0, 10.0]          # corrélation ~1
    opp = [5.0, 1.0, 4.0, 2.0, 3.0]            # peu corrélé
    assert too_correlated(base, [same], max_corr=0.8) is True
    assert too_correlated(base, [opp], max_corr=0.8) is False


def test_drawdown_stop():
    assert drawdown_stop_triggered([100, 105, 110, 98], max_dd_pct=0.10) is True   # -10.9%
    assert drawdown_stop_triggered([100, 101, 102, 103], max_dd_pct=0.10) is False


def test_risk_parity_favors_low_vol():
    w = risk_parity_weights([0.1, 0.2, 0.1])
    assert abs(sum(w) - 1.0) < 1e-9
    assert w[0] > w[1] and w[2] > w[1]        # les moins volatils pèsent plus


def test_exposure_cap():
    assert exposure_ok([100, 200], 100, max_total=500) is True
    assert exposure_ok([100, 200], 300, max_total=500) is False
