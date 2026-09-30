"""M4 dé-risquage liquidation graduel + M5 budget funding."""
from __future__ import annotations

import pytest

from hl_observer.risk.carry_risk_gates import fraction_derisk, budget_funding_depasse


def test_derisk_graduel():
    assert fraction_derisk(0.8) == 1.0                 # tampon large -> plein
    assert fraction_derisk(0.1) == 0.0                 # au plancher -> a plat
    assert fraction_derisk(0.3) == pytest.approx(0.5)  # mi-chemin entre 0.1 et 0.5


def test_budget_funding():
    assert budget_funding_depasse(30.0, budget_bps=20.0) is True
    assert budget_funding_depasse(10.0, budget_bps=20.0) is False
