"""[lot2 #91] quote-quantity pretrade : notional réel après conversion pour une taille en quote."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.risk_gates.quote_quantity_pretrade import notional_reel, valider   # noqa: E402


def test_taille_quote_est_le_notional():
    r = notional_reel(500.0, unite="QUOTE")
    assert r["notional"] == 500.0


def test_taille_base_convertie():
    r = notional_reel(2.0, unite="BASE", prix=100.0)
    assert r["notional"] == 200.0
    assert notional_reel(2.0, unite="BASE")["notional"] == "UNMEASURABLE"   # prix requis


def test_validation_limite():
    assert valider(2.0, unite="BASE", prix=100.0, notional_max=150.0)["ok"] is False
    assert valider(2.0, unite="BASE", prix=100.0, notional_max=250.0)["ok"] is True
