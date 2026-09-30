"""Tests des outils de robustesse honnetes (purs, deterministes)."""
from __future__ import annotations

from hl_observer.backtesting.robustness import (
    bootstrap_pnl_ci,
    maker_adjust_net,
    profit_factor,
)


def test_profit_factor():
    assert profit_factor([10, -5, 5]) == 3.0
    assert profit_factor([-1, -2]) == 0.0
    assert profit_factor([]) == 0.0


def test_bootstrap_is_deterministic_and_bounds_make_sense():
    trades = [1.0, -1.0, 2.0, -0.5, 0.5] * 20
    a = bootstrap_pnl_ci(trades, n=500, seed=3)
    b = bootstrap_pnl_ci(trades, n=500, seed=3)
    assert a == b  # deterministe
    assert a["trades"] == 100
    assert a["net_p5"] <= a["net_median"] <= a["net_p95"]
    assert 0.0 <= a["prob_net_positive"] <= 1.0


def test_bootstrap_flags_fragile_result():
    # sequence a net ~0 et forte variance => proba net positif proche de 0.5 (fragile)
    trades = [50.0, -49.0] * 30
    r = bootstrap_pnl_ci(trades, n=1000, seed=1)
    assert 0.2 < r["prob_net_positive"] < 0.8


def test_maker_saving_helps_but_missed_fills_cost():
    trades = [1.0, -1.0, 2.0, -2.0, 0.5, -0.5]
    # 100% rempli + economie => chaque trade +0.5 => net augmente de 6*0.5=3
    full = maker_adjust_net(trades, spread_saving_usd=0.5, fill_rate=1.0)
    assert round(sum(full) - sum(trades), 6) == 3.0
    # 50% rempli en mode ADVERSE => on garde les 3 pires (apres +0.5)
    adv = maker_adjust_net(trades, spread_saving_usd=0.5, fill_rate=0.5, adverse=True)
    assert len(adv) == 3
    assert adv == sorted([t + 0.5 for t in trades])[:3]


def test_maker_random_fill_deterministic():
    trades = [float(i) for i in range(10)]
    a = maker_adjust_net(trades, spread_saving_usd=0.0, fill_rate=0.6, seed=9)
    b = maker_adjust_net(trades, spread_saving_usd=0.0, fill_rate=0.6, seed=9)
    assert a == b and len(a) == 6
