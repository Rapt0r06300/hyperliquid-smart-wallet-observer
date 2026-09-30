"""[ARB lot2 #9] matrice TIF par venue : combinaison absente = interdite (fail-closed)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle import time_in_force_matrix as TIF   # noqa: E402


def test_tif_autorise():
    assert TIF.tif_autorise("HL", TIF.POST_ONLY)["autorise"] is True
    assert TIF.tif_autorise("BINANCE", TIF.IOC)["autorise"] is True


def test_tif_interdit_sur_venue():
    r = TIF.tif_autorise("BINANCE", TIF.GTD)             # GTD absent de BINANCE dans la matrice défaut
    assert r["autorise"] is False and r["raison"] == "TIF_INTERDIT_SUR_CETTE_VENUE"


def test_venue_inconnue_failclosed():
    assert TIF.tif_autorise("KRAKEN", TIF.GTC)["autorise"] is False
    assert TIF.tif_autorise("HL", "ZZZ")["autorise"] is False
