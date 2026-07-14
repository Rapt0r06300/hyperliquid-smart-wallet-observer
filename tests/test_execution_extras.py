"""Tests exécution avancée."""
from __future__ import annotations

from hl_observer.backtesting.execution_extras import (
    funding_cost,
    iceberg_slices,
    partial_fill,
    sample_latency_ms,
)


def test_iceberg_slices():
    s = iceberg_slices(100.0, 30.0)
    assert abs(sum(s) - 100.0) < 1e-9
    assert s[:3] == [30.0, 30.0, 30.0] and abs(s[-1] - 10.0) < 1e-9


def test_latency_sampler_bounds_and_determinism():
    a = sample_latency_ms(mean_ms=50, jitter_ms=10, seed=1, n=100)
    b = sample_latency_ms(mean_ms=50, jitter_ms=10, seed=1, n=100)
    assert a == b and all(x >= 0.0 for x in a)


def test_partial_fill():
    assert partial_fill(100.0, 40.0) == {"filled": 40.0, "unfilled": 60.0}
    assert partial_fill(100.0, 250.0) == {"filled": 100.0, "unfilled": 0.0}


def test_funding_cost():
    # 1000$ à 0.5 bps/h pendant 8h = 1000 * 0.00005 * 8 = 0.4$
    assert abs(funding_cost(1000.0, funding_rate_per_hour_bps=0.5, hours_held=8.0) - 0.4) < 1e-9
