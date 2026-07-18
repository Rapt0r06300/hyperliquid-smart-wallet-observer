"""O2/O3/O4 — Monte Carlo equity, stabilité paramètres, perf par régime."""
from __future__ import annotations

import random

from hl_observer.backtesting.monte_carlo import bootstrap_equity, stabilite_parametre, perf_par_regime


def test_bootstrap_donne_des_intervalles():
    pnls = [1.0, -1.0, 2.0, -0.5, 1.5, -2.0, 3.0, 0.5]
    r = bootstrap_equity(pnls, n_sim=500, rng=random.Random(1))
    assert r["pnl_p05"] <= r["pnl_median"] <= r["pnl_p95"]
    assert 0.0 <= r["prob_pnl_negatif"] <= 1.0
    assert r["drawdown_p95"] >= 0.0


def test_bootstrap_deny_by_default():
    assert bootstrap_equity([1.0, 2.0]) is None


def test_stabilite_plateau_vs_pic():
    plateau = stabilite_parametre({1.0: 8.0, 2.0: 10.0, 3.0: 9.0})   # voisins ~aussi bons
    assert plateau["plateau"] is True and plateau["meilleur_param"] == 2.0
    pic = stabilite_parametre({1.0: 1.0, 2.0: 10.0, 3.0: 1.0})       # pic isole -> overfit
    assert pic["plateau"] is False


def test_perf_par_regime():
    out = perf_par_regime({"bull": [1.0, 2.0, 3.0], "bear": [-1.0, -2.0]})
    assert "bull" in out and "bear" in out and "sharpe" in out["bull"]
