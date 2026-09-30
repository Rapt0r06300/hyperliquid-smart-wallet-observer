"""M6 divergence de sources + M7 levier par régime."""
from __future__ import annotations

import pytest

from hl_observer.risk.safety_gates_mm import divergence_max_frac, mode_sur, levier_max_regime


def test_divergence_et_safe_mode():
    assert mode_sur([100.0, 100.5, 100.2]) is True         # <1% -> sur
    assert mode_sur([100.0, 105.0]) is False               # 5% -> SAFE MODE
    assert mode_sur([100.0]) is False                       # 1 source -> non mesurable -> prudent


def test_divergence_valeur():
    assert divergence_max_frac([100.0, 102.0, 100.0]) == pytest.approx(0.02)


def test_levier_par_regime():
    assert levier_max_regime("EXPANSION") == 2.0
    assert levier_max_regime("CONTRACTION") == 10.0
    assert levier_max_regime("INCONNU", base=5.0) == 5.0
