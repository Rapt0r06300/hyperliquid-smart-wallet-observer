"""Tests traitement du signal & cointégration."""
from __future__ import annotations

import random

from hl_observer.backtesting.signal_processing import engle_granger_spread, haar_wavelet_transform
from hl_observer.backtesting.safety_defaults import safe_default_decision


def test_haar_detail_zero_on_constant():
    _, detail = haar_wavelet_transform([5.0, 5.0, 5.0, 5.0])
    assert all(abs(d) < 1e-9 for d in detail)
    _, detail2 = haar_wavelet_transform([4.0, 2.0, 6.0, 4.0])
    assert any(abs(d) > 0.1 for d in detail2)


def test_cointegration_detects_relationship():
    rng = random.Random(0)
    b, acc = [], 0.0
    for _ in range(400):
        acc += rng.gauss(0, 1)
        b.append(acc)
    a = [2.0 * b[i] + rng.gauss(0, 0.5) for i in range(len(b))]   # a = 2b + bruit stationnaire
    r = engle_granger_spread(a, b)
    assert abs(r["beta"] - 2.0) < 0.3                              # retrouve la relation
    assert r["spread_autocorr"] < 0.6                             # spread mean-reverting (cointégré)


def test_failsafe_default_no_trade():
    assert safe_default_decision(False)["decision"] == "NO_TRADE"
    assert safe_default_decision(True)["decision"] == "EVALUATE"
