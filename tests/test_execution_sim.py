"""Tests simulation d'exécution fine."""
from __future__ import annotations

from hl_observer.backtesting.execution_sim import queue_position, tick_backtest


def test_queue_position_counts_priority():
    book = [(101.0, 5.0), (100.0, 10.0), (99.0, 3.0)]   # bids
    # ordre BUY à 100 : devant = 101 (5, meilleur) + 100 (10, égal) = 15
    assert queue_position(100.0, book, side="BUY") == 15.0


def test_tick_backtest_long_wins_on_uptrend():
    prices = [100.0 * (1.0 + 0.001 * i) for i in range(200)]
    r = tick_backtest(prices, lambda past: 1, cost_bps=0.0)   # toujours long
    assert r["gross"] > 0 and r["net"] == r["gross"]          # 0 coût car 1 seul changement de pos
