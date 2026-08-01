"""[ARB #19] depth reservation : deux opportunités ne peuvent pas consommer deux fois la même profondeur."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.depth_reservation import ReservationCarnet   # noqa: E402


def test_double_consommation_impossible():
    rc = ReservationCarnet()
    a = rc.reserver("HL", "BTC", 65000.0, 3000.0, affiche_usd=5000.0)
    assert a["pris_usd"] == 3000.0
    b = rc.reserver("HL", "BTC", 65000.0, 3000.0, affiche_usd=5000.0)
    assert b["pris_usd"] == 2000.0 and b["refuse_usd"] == 1000.0   # reste 2000 seulement


def test_disponible_diminue():
    rc = ReservationCarnet()
    rc.reserver("HL", "BTC", 65000.0, 3000.0, affiche_usd=5000.0)
    assert rc.disponible("HL", "BTC", 65000.0, affiche_usd=5000.0) == 2000.0


def test_niveaux_independants():
    rc = ReservationCarnet()
    rc.reserver("HL", "BTC", 65000.0, 5000.0, affiche_usd=5000.0)
    assert rc.disponible("HL", "BTC", 65001.0, affiche_usd=4000.0) == 4000.0   # autre niveau intact
