"""Tests du zoo de mecanismes (purs, deterministes, no-lookahead)."""
from __future__ import annotations

from hl_observer.backtesting.mechanism_zoo import (
    breakout,
    buy_hold,
    momentum,
    random_strategy,
)


def test_reports_have_expected_shape():
    px = [100.0 + (i % 7) for i in range(300)]
    for r in (momentum(px), breakout(px), buy_hold(px), random_strategy(px, seed=1)):
        assert set(r) == {"trades", "net_usd", "win_rate", "profit_factor", "max_drawdown_usd"}


def test_momentum_and_buyhold_win_on_clean_uptrend_pre_cost():
    px = [100.0 * (1.0 + 0.001 * i) for i in range(400)]
    assert momentum(px, cost_bps=0.0)["net_usd"] > 0     # suivre la tendance gagne en tendance
    assert buy_hold(px, cost_bps=0.0)["net_usd"] > 0


def test_random_is_deterministic_by_seed():
    px = [100.0 + ((i * 7) % 11) for i in range(400)]
    assert random_strategy(px, seed=3) == random_strategy(px, seed=3)


def test_costs_hurt():
    px = [100.0 * (1.0 + 0.001 * i) for i in range(400)]
    assert momentum(px, cost_bps=10.0)["net_usd"] < momentum(px, cost_bps=0.0)["net_usd"]
