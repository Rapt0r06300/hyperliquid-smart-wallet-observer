"""I6 — funding extrême -> retournement contrarian (réutilise le z-score A4)."""
from __future__ import annotations

from hl_observer.signals.funding_reversal import signal_reversal


def test_funding_tres_haut_biais_short():
    assert signal_reversal(3.0) == "SHORT"      # longs surpeuplés -> fade
    assert signal_reversal(2.0) == "SHORT"


def test_funding_tres_bas_biais_long():
    assert signal_reversal(-2.5) == "LONG"


def test_funding_normal_pas_de_signal():
    assert signal_reversal(0.5) is None
    assert signal_reversal(-1.0) is None


def test_entree_invalide():
    assert signal_reversal("x") is None
