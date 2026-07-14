"""Tests reversion a la moyenne — gagne en range (oscillation), perd en tendance. No-lookahead, pur."""
from __future__ import annotations

import math

from hl_observer.backtesting.mean_reversion import MRConfig, simulate_mean_reversion


def test_ranging_series_is_profitable_pre_and_post_small_cost():
    px = [100.0 + 3.0 * math.sin(i / 5.0) for i in range(600)]
    r = simulate_mean_reversion(px, MRConfig(lookback=30, entry_z=1.5, exit_z=0.3, cost_bps=2.0))
    assert r["trades"] > 0
    assert r["net_usd"] > 0


def test_strong_trend_loses():
    # rampe lineaire : le z plafonne a ~1.73 (sqrt(12)/2), donc entry_z doit etre < ~1.73 pour declencher.
    px = [100.0 * (1.0 + 0.002 * i) for i in range(400)]
    r = simulate_mean_reversion(px, MRConfig(lookback=30, entry_z=1.5, cost_bps=6.0))
    assert r["trades"] > 0
    assert r["net_usd"] < 0


def test_costs_reduce_net():
    px = [100.0 + 3.0 * math.sin(i / 5.0) for i in range(600)]
    cheap = simulate_mean_reversion(px, MRConfig(lookback=30, entry_z=1.5, cost_bps=0.0))
    dear = simulate_mean_reversion(px, MRConfig(lookback=30, entry_z=1.5, cost_bps=10.0))
    assert dear["net_usd"] < cheap["net_usd"]


def test_deterministic():
    px = [100.0 + 2.0 * math.sin(i / 7.0) for i in range(300)]
    assert simulate_mean_reversion(px, MRConfig()) == simulate_mean_reversion(px, MRConfig())
