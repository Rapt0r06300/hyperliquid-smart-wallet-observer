"""[pépite 232] primary + secondary hedge route : chaque opportunité a un principal ET un secours distinct."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.routing.primary_secondary_hedge_route import preparer   # noqa: E402


def test_deux_routes_distinctes():
    assert preparer(route_principale="HL", route_secours="BINANCE")["pret"] is True


def test_secours_manquant():
    r = preparer(route_principale="HL", route_secours=None)
    assert r["pret"] is False and r["raison"] == "ROUTE_SECOURS_MANQUANTE"


def test_secours_identique():
    r = preparer(route_principale="HL", route_secours="HL")
    assert r["pret"] is False and r["raison"] == "SECOURS_IDENTIQUE_AU_PRINCIPAL"
