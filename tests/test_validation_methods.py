"""Tests des méthodes de validation avancées (propriétés, cas construits)."""
from __future__ import annotations

from hl_observer.backtesting.validation_methods import (
    min_track_record_length,
    probability_of_backtest_overfitting,
    stationary_bootstrap,
)


def test_stationary_bootstrap_deterministic_and_sized():
    x = [1.0, -1.0, 2.0, 0.5] * 30
    a = stationary_bootstrap(x, mean_block=8, n=200, seed=5)
    b = stationary_bootstrap(x, mean_block=8, n=200, seed=5)
    assert a == b and len(a) == 200


def test_min_track_record_length_shorter_for_higher_sharpe():
    assert min_track_record_length(2.0) < min_track_record_length(0.5)
    assert min_track_record_length(0.0) == float("inf")     # SR nul -> jamais prouvable


def test_pbo_detects_overfit_vs_genuine():
    S, N = 6, 6
    # SUR-APPRIS : chaque config ne "gagne" qu'une seule période (bruit) -> PBO élevé
    overfit = [[1.0 if s == c else 0.0 for c in range(N)] for s in range(S)]
    # ROBUSTE : la config 0 gagne partout -> PBO ~ 0
    genuine = [[1.0 if c == 0 else 0.0 for c in range(N)] for _ in range(S)]
    assert probability_of_backtest_overfitting(overfit) > 0.8
    assert probability_of_backtest_overfitting(genuine) < 0.2
