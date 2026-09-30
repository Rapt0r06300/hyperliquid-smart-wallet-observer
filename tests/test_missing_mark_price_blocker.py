"""[lot2 #92] missing-mark-price blocker : un instrument sans mark rend l'equity non déclarable."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.risk_gates.missing_mark_price_blocker import equity_complete   # noqa: E402


def test_tous_les_marks_presents():
    r = equity_complete({"BTC": 0.5, "ETH": -2.0}, {"BTC": 65000.0, "ETH": 3000.0})
    assert r["complete"] is True


def test_mark_manquant_bloque():
    r = equity_complete({"BTC": 0.5, "ETH": -2.0}, {"BTC": 65000.0})
    assert r["complete"] is False and "ETH" in r["instruments_sans_mark"]


def test_position_nulle_pas_besoin_de_mark():
    r = equity_complete({"BTC": 0.5, "XRP": 0.0}, {"BTC": 65000.0})
    assert r["complete"] is True                          # XRP a 0, pas besoin de mark
