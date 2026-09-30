"""[ARB #35] failure taxonomy : chaque échec est classé ; un échec non reconnu reste UNKNOWN_STATE."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage import failure_taxonomy as FT   # noqa: E402


def test_categories_specifiques():
    assert FT.classifier("order TIMED_OUT")["categorie"] == FT.TIMEOUT
    assert FT.classifier("STALE quote")["categorie"] == FT.STALE_PRICE
    assert FT.classifier("MIN_NOTIONAL not met")["categorie"] == FT.INVALID_QUANTITY
    assert FT.classifier("socket DISCONNECT")["categorie"] == FT.CONNECTOR_FAILURE


def test_reject_generique():
    r = FT.classifier("order REJECTED by venue")
    assert r["categorie"] == FT.REJECT and r["reconnue"] is True


def test_inconnu_reste_unknown():
    r = FT.classifier("banana")
    assert r["categorie"] == FT.UNKNOWN_STATE and r["reconnue"] is False
