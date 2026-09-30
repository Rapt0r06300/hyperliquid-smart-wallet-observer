"""Tests des méthodes quantitatives (propriétés, déterminisme)."""
from __future__ import annotations

import math
import random

from hl_observer.backtesting.quant_methods import (
    block_bootstrap,
    deflated_sharpe,
    fractional_diff,
    hurst_exponent,
    shannon_entropy,
)


def test_block_bootstrap_deterministic_and_sized():
    x = [1.0, -1.0, 2.0, -0.5] * 25
    a = block_bootstrap(x, block=5, n=300, seed=3)
    b = block_bootstrap(x, block=5, n=300, seed=3)
    assert a == b and len(a) == 300


def test_fractional_diff_shapes_and_extremes():
    xs = [float(i) for i in range(50)]
    d1 = fractional_diff(xs, 1.0)          # ~ première différence
    assert len(d1) < len(xs)
    assert all(abs(v - 1.0) < 1e-6 for v in d1[1:])  # diff d'une rampe = 1


def test_deflated_sharpe_monotone_in_trials():
    high = deflated_sharpe(1.0, 500, 2)
    low = deflated_sharpe(1.0, 500, 1000)
    assert 0.0 <= low <= high <= 1.0        # plus d'essais => seuil plus dur => PSR plus basse


def test_hurst_distinguishes_persistent_from_meanreversion():
    # PERSISTANT (incréments positivement auto-corrélés) -> cumul H>0.5
    rng = random.Random(1)
    inc = 0.0
    acc = 0.0
    persistent = []
    for _ in range(600):
        inc = 0.8 * inc + rng.gauss(0.0, 1.0)
        acc += inc
        persistent.append(acc)
    # MEAN-REVERTING (oscillation bornée) -> H<0.5
    mr = [math.sin(i / 3.0) for i in range(600)]
    assert hurst_exponent(persistent) > 0.5
    assert hurst_exponent(mr) < 0.5


def test_shannon_entropy_bounds():
    const = [5.0] * 100
    spread = [float(i % 10) for i in range(200)]
    assert shannon_entropy(const) == 0.0
    assert shannon_entropy(spread) > 1.0
