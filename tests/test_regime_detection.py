"""Tests de la détection de régime."""
from __future__ import annotations

import random
from statistics import pstdev

from hl_observer.backtesting.regime_detection import (
    cusum_change_points,
    garch11_variance,
    kalman_filter_1d,
)


def test_kalman_smooths_noise():
    rng = random.Random(0)
    noisy = [10.0 + rng.gauss(0, 1.0) for _ in range(300)]
    smooth = kalman_filter_1d(noisy, process_var=1e-3, obs_var=1.0)
    assert pstdev(smooth) < pstdev(noisy)          # sortie plus lisse
    assert abs(smooth[-1] - 10.0) < 1.0            # converge vers le vrai niveau


def test_garch_reacts_to_shock():
    rets = [0.001] * 30 + [0.15] + [0.001] * 30
    var = garch11_variance(rets)
    assert var[40] > var[20]                       # variance élevée après le choc


def test_cusum_detects_level_shift():
    series = [0.0] * 40 + [10.0] * 40
    pts = cusum_change_points(series, threshold=5.0)
    assert any(38 <= p <= 45 for p in pts)         # rupture détectée près de l'indice 40
