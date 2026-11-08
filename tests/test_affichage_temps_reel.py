"""Tests du formateur de fills de l'affichage temps réel."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import affichage_temps_reel as A  # noqa: E402


def test_sens_depuis_signe():
    assert "ACHAT" in A.formater_fill({"coin": "ETH", "px": "1", "sz": "1", "signe": 1})
    assert "VENTE" in A.formater_fill({"coin": "ETH", "px": "1", "sz": "1", "signe": -1})


def test_sens_depuis_side_et_aggressor():
    assert "ACHAT" in A.formater_fill({"coin": "ETH", "px": 1, "sz": 1, "side": "B"})
    assert "VENTE" in A.formater_fill({"coin": "ETH", "px": 1, "sz": 1, "side": "A"})
    assert "VENTE" in A.formater_fill({"coin": "ETH", "price": 1, "size": 1, "aggressor_side": "SELL"})


def test_rejet_si_incomplet():
    assert A.formater_fill({"coin": "ETH"}) is None
    assert A.formater_fill({"px": "1", "sz": "1"}) is None
