"""Q1/Q2/Q3 — métriques risque, décroissance, queue."""
from __future__ import annotations

import pytest

from hl_observer.backtesting import perf_metrics as m


def test_sharpe_et_sortino():
    pnls = [1.0, 1.0, 1.0, 1.0]
    assert m.sharpe(pnls) == 0.0                    # pas de variance
    assert m.sortino([1.0, -1.0, 1.0, -1.0]) is not None


def test_profit_factor_et_payoff():
    assert m.profit_factor([10.0, -5.0]) == pytest.approx(2.0)
    assert m.payoff([10.0, 10.0, -5.0]) == pytest.approx(2.0)


def test_max_drawdown_et_recuperation():
    # equity: 0,10,5,15 -> pic 10, creux 5 -> dd 5 ; recupere a 15
    pnls = [10.0, -5.0, 10.0]
    assert m.max_drawdown(pnls) == pytest.approx(5.0)
    assert m.temps_recuperation(pnls) is not None


def test_calmar():
    assert m.calmar([10.0, -5.0, 10.0]) == pytest.approx(15.0 / 5.0)


def test_q2_decroissance_roulante():
    # 20 bons puis 20 mauvais -> la fenetre recente decroche
    pnls = [5.0] * 20 + [0.1] * 20
    assert m.perf_roulante_decroit(pnls, fenetre=20, fraction=0.5) is True
    assert m.perf_roulante_decroit([5.0] * 40, fenetre=20) is False


def test_q2_global_non_positif_ne_declenche_pas_de_decroissance():
    assert m.perf_roulante_decroit([-1.0] * 40, fenetre=20) is False
    assert m.perf_roulante_decroit([1.0, -1.0] * 20, fenetre=20) is False


def test_deny_by_default():
    assert m.sharpe([1.0]) is None and m.payoff([1.0]) is None
