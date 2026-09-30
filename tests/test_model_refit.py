"""K4 — cadence de re-fit + moniteur de décroissance."""
from __future__ import annotations

from hl_observer.modeling.model_refit import (
    RESTE, REFIT_CADENCE, REFIT_DECROISSANCE, decroissance_detectee, decision_refit,
)

H = 3_600_000


def test_decroissance():
    assert decroissance_detectee(10.0, 3.0, fraction_min=0.5) is True    # 3 < 5
    assert decroissance_detectee(10.0, 8.0, fraction_min=0.5) is False   # 8 > 5
    assert decroissance_detectee(-1.0, -5.0) is False                    # ref <=0 -> pas juge


def test_refit_sur_decroissance_prioritaire():
    assert decision_refit(0, 0, intervalle_ms=100 * H, perf_reference=10.0, perf_recente=2.0) == REFIT_DECROISSANCE


def test_refit_sur_cadence():
    assert decision_refit(200 * H, 0, intervalle_ms=100 * H) == REFIT_CADENCE


def test_reste_si_rien():
    assert decision_refit(1 * H, 0, intervalle_ms=100 * H, perf_reference=10.0, perf_recente=9.0) == RESTE
