"""Le chemin numpy et le fallback Python pur doivent donner LE MÊME résultat."""
from __future__ import annotations

import random

from hl_observer.backtesting.vectorized import fast_drawdown, fast_pnl, fast_rolling_vol


def test_pnl_numpy_equals_pure_python():
    rng = random.Random(1)
    e = [100.0 + rng.random() for _ in range(300)]
    x = [100.0 + rng.random() for _ in range(300)]
    s = [rng.choice([1, -1]) for _ in range(300)]
    a = fast_pnl(e, x, s, use_numpy=True)
    b = fast_pnl(e, x, s, use_numpy=False)
    assert len(a) == len(b)
    assert all(abs(u - v) < 1e-9 for u, v in zip(a, b))


def test_costs_are_charged():
    # entrée = sortie -> le seul PnL possible est le COÛT (négatif)
    p = fast_pnl([100.0], [100.0], [1], notional=500.0, cost_bps=6.0)
    assert abs(p[0] - (-0.30)) < 1e-9


def test_drawdown_both_paths():
    eq = [1000.0, 1020.0, 980.0, 1005.0, 950.0]
    assert abs(fast_drawdown(eq, use_numpy=True) - 70.0) < 1e-9
    assert abs(fast_drawdown(eq, use_numpy=False) - 70.0) < 1e-9


def test_rolling_vol_both_paths():
    rng = random.Random(2)
    p, acc = [], 100.0
    for _ in range(120):
        acc *= 1 + rng.gauss(0, 0.01)
        p.append(acc)
    a = fast_rolling_vol(p, window=20, use_numpy=True)
    b = fast_rolling_vol(p, window=20, use_numpy=False)
    assert all(abs(u - v) < 1e-9 for u, v in zip(a, b))
    assert max(a) > 0


def test_rolling_vol_short_inputs_are_empty():
    assert fast_rolling_vol([]) == []
    assert fast_rolling_vol([100.0]) == []
