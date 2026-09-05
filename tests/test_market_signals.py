"""Tests des signaux de marché."""
from __future__ import annotations

import math
import random

from hl_observer.backtesting.market_signals import (
    anomaly_zscores,
    dominant_cycle,
    rolling_correlation,
)


def test_rolling_correlation():
    a = [float(i) for i in range(50)]
    b = [2.0 * i + 1.0 for i in range(50)]        # parfaitement corrélé
    assert rolling_correlation(a, b, window=30) > 0.99


def test_rolling_correlation_returns_zero_with_insufficient_history():
    assert rolling_correlation([1.0], [2.0], window=30) == 0.0


def test_anomaly_detects_spike():
    rng = random.Random(0)
    series = [10.0 + rng.gauss(0.0, 0.1) for _ in range(60)]   # bruit léger -> sd>0
    series[45] = 25.0                                          # spike net
    idx = anomaly_zscores(series, window=30, threshold=3.0)
    assert 45 in idx


def test_dominant_cycle_finds_period():
    period = 20
    series = [math.sin(2 * math.pi * t / period) for t in range(200)]
    dc = dominant_cycle(series)
    assert dc is not None and abs(dc - period) < 2.0
