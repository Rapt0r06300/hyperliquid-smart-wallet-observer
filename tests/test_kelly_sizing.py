"""E22 — Kelly fractionnaire : monter où l'edge/risque est bon, plafonner, 0 sans edge."""
from __future__ import annotations

import pytest

from hl_observer.risk.kelly_sizing import (
    FRACTION_KELLY, PLAFOND_FRACTION, kelly_continu, kelly_discret,
    fraction_capital_continu, fraction_capital_discret,
)


def test_kelly_continu_edge_sur_variance():
    assert kelly_continu(0.02, 0.04) == pytest.approx(0.5)
    assert kelly_continu(-0.01, 0.04) == 0.0        # edge negatif -> 0
    assert kelly_continu(0.02, 0.0) == 0.0          # variance nulle -> 0


def test_kelly_discret_formule():
    # p=0.6, b=2 -> 0.6 - 0.4/2 = 0.4
    assert kelly_discret(0.6, 2.0) == pytest.approx(0.4)
    assert kelly_discret(0.4, 1.0) == 0.0           # 0.4 - 0.6 = -0.2 -> borne 0


def test_fraction_applique_le_quart_et_le_plafond():
    # kelly plein 0.5 * 0.25 = 0.125
    assert fraction_capital_continu(0.02, 0.04) == pytest.approx(0.125)
    # kelly enorme -> borne au plafond
    assert fraction_capital_continu(1.0, 0.001, fraction=1.0) == pytest.approx(PLAFOND_FRACTION)


def test_zero_sans_edge():
    assert fraction_capital_continu(-1.0, 0.04) == 0.0
    assert fraction_capital_discret(0.3, 1.0) == 0.0
