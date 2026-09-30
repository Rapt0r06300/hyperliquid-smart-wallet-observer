"""I2 (déséquilibre agresseurs) + I7 (variation d'open interest)."""
from __future__ import annotations

import pytest

from hl_observer.signals.microstructure_signals import (
    desequilibre_agresseurs, variation_oi, interpretation_oi,
)


def test_desequilibre_acheteur():
    trades = [{"aggressor": "BUY", "size": 30}, {"aggressor": "SELL", "size": 10}]
    assert desequilibre_agresseurs(trades) == pytest.approx(0.5)   # (30-10)/40


def test_desequilibre_equilibre_et_vide():
    assert desequilibre_agresseurs([{"aggressor": "BUY", "size": 5}, {"aggressor": "SELL", "size": 5}]) == 0.0
    assert desequilibre_agresseurs([]) is None


def test_variation_oi():
    assert variation_oi(110.0, 100.0) == pytest.approx(0.1)
    assert variation_oi(100.0, 0.0) is None


def test_interpretation_oi():
    assert interpretation_oi(0.05, 0.03) == "TENDANCE_SAINE"     # OI+ prix+ 
    assert interpretation_oi(0.05, 0.0) == "LEVIER_FRAGILE"      # OI+ prix plat -> fragile
    assert interpretation_oi(-0.05, 0.03) == "DELEVERAGING"      # OI- -> positions se ferment
