"""Tests des stratégies supplémentaires + métriques de marché."""
from __future__ import annotations

import math
import random

from hl_observer.backtesting.market_metrics import l2_reconstruct, long_short_ratio, oi_change
from hl_observer.backtesting.strategies_extra import (
    cross_market_momentum,
    pairs_trade_signal,
    rebalancing_premium,
)


def test_pairs_signal_on_diverging_spread():
    rng = random.Random(0)
    b, acc = [], 0.0
    for _ in range(200):
        acc += rng.gauss(0, 1)
        b.append(100.0 + acc)
    a = [2.0 * b[i] + rng.gauss(0, 0.5) for i in range(len(b))]
    a[-1] -= 10.0                                  # spread s'effondre -> A sous-évalué
    r = pairs_trade_signal(a, b, entry_z=1.5)
    assert r["signal"] == 1                        # long A / short B (retour attendu)


def test_rebalancing_captures_volatility():
    # 2 actifs qui oscillent en OPPOSITION -> le rebalancement capture la volatilité
    a = [100.0 * (1 + 0.2 * math.sin(t / 5.0)) for t in range(300)]
    b = [100.0 * (1 - 0.2 * math.sin(t / 5.0)) for t in range(300)]
    r = rebalancing_premium(a, b, rebalance_every=5)
    assert r["premium"] > 0                        # prime de rebalancement positive


def test_cross_market_momentum_runs():
    leader = [100.0 * (1 + 0.001 * t) for t in range(200)]
    follower = [50.0 * (1 + 0.001 * t) for t in range(200)]   # suit parfaitement
    r = cross_market_momentum(leader, follower, lookback=20, hold=10, cost_bps=0.0)
    assert r["trades"] > 0 and r["net_usd"] > 0


def test_l2_reconstruct():
    snap = {100.0: 5.0, 99.5: 3.0}
    book = l2_reconstruct(snap, [(100.0, 0.0), (99.0, 7.0)])   # supprime 100, ajoute 99
    assert 100.0 not in book and book[99.0] == 7.0 and book[99.5] == 3.0


def test_oi_and_ls_ratio():
    assert abs(oi_change([100.0, 110.0]) - 0.1) < 1e-9
    assert long_short_ratio(60, 40) == 1.5
    assert long_short_ratio(10, 0) == float("inf")
