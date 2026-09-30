"""Tests du simulateur grid/MM — le grind gagne en range, le tail (stop dur) perd en tendance."""
from __future__ import annotations

from hl_observer.backtesting.grid_market_maker import GridConfig, simulate_grid


def test_ranging_market_grinds_wins_without_blowup():
    px = []
    for _ in range(40):
        px += [100.0, 100.5, 100.0, 99.6, 100.0, 100.6]
    r = simulate_grid(px, GridConfig(grid_bps=30, tp_bps=30, max_adds=6, hard_stop_bps=300, add_size_mult=1.0))
    assert r["wins"] > 0
    assert r["blowups"] == 0
    assert r["net_usd"] > 0


def test_trend_down_triggers_hard_stop_tail_loss():
    px = [100.0 * (1.0 - 0.004 * i) for i in range(120)]
    r = simulate_grid(px, GridConfig(grid_bps=30, tp_bps=30, max_adds=6, hard_stop_bps=300, add_size_mult=1.0))
    assert r["blowups"] >= 1
    assert r["net_usd"] < 0
    assert r["max_drawdown_usd"] > 0


def test_martingale_amplifies_the_tail():
    px = [100.0 * (1.0 - 0.004 * i) for i in range(120)]
    grid = simulate_grid(px, GridConfig(add_size_mult=1.0))
    martingale = simulate_grid(px, GridConfig(add_size_mult=2.0))
    assert martingale["net_usd"] <= grid["net_usd"]


def test_adverse_fill_cost_reduces_net():
    px = []
    for _ in range(40):
        px += [100.0, 100.5, 100.0, 99.6, 100.0, 100.6]
    optimiste = simulate_grid(px, GridConfig(adverse_bps=0.0))
    realiste = simulate_grid(px, GridConfig(adverse_bps=5.0))
    assert realiste["net_usd"] < optimiste["net_usd"]


def test_deterministic():
    px = [100.0, 100.5, 99.7, 100.4, 99.9, 100.6, 99.5, 100.7] * 10
    assert simulate_grid(px, GridConfig()) == simulate_grid(px, GridConfig())
