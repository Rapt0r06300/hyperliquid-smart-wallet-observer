"""S5 — scaling capital selon drawdown (progressif)."""
from __future__ import annotations

import pytest

from hl_observer.risk.drawdown_scaling import facteur_capital


def test_scaling():
    assert facteur_capital(0.02) == 1.0                 # dd faible -> plein
    assert facteur_capital(0.30, taille_min=0.2) == 0.2  # dd fort -> minimal
    assert facteur_capital(0.15, dd_debut=0.05, dd_plancher=0.25, taille_min=0.2) == pytest.approx(0.6)
