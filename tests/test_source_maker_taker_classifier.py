"""[pépite 280] source maker/taker classifier : séparer les fills qui fournissent la liquidité de ceux qui la prennent."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.source_maker_taker_classifier import classer   # noqa: E402


def test_is_maker_explicite():
    assert classer({"is_maker": True})["classe"] == "MAKER"
    assert classer({"is_maker": False})["classe"] == "TAKER"


def test_crossed_hyperliquid():
    assert classer({"crossed": True})["classe"] == "TAKER"
    assert classer({"crossed": False})["classe"] == "MAKER"


def test_aucun_signal_unmeasurable():
    assert classer({"prix": 100.0})["classe"] == "UNMEASURABLE"
