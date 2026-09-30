"""I8 — régime de volatilité : expansion / contraction / normal."""
from __future__ import annotations

import pytest

from hl_observer.signals.vol_regime_signal import vol_realisee, regime_vol


def test_vol_realisee():
    assert vol_realisee([1.0, 1.0, 1.0]) == pytest.approx(0.0)
    assert vol_realisee([0.0]) is None
    assert vol_realisee([1.0, -1.0]) == pytest.approx(1.0)


def test_regimes():
    assert regime_vol(3.0, 1.0) == "EXPANSION"       # courte >> longue
    assert regime_vol(0.5, 1.0) == "CONTRACTION"     # courte << longue
    assert regime_vol(1.1, 1.0) == "NORMAL"
    assert regime_vol(1.0, 0.0) is None              # vol longue nulle -> non mesurable
