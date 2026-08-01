"""[pépite 214] intent ID != venue order ID : une intention porte plusieurs venue-ids, reste une position."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.intent_vs_venue_id import RegistreIntentVenue   # noqa: E402


def test_une_position_plusieurs_venue_ids():
    r = RegistreIntentVenue()
    r.lier(intent_id="I1", venue_order_id="v1")
    r.lier(intent_id="I1", venue_order_id="v2")           # remplacement -> nouveau venue-id
    assert r.n_positions_distinctes() == 1                # UNE intention, pas deux
    assert r.venues_de("I1") == ["v1", "v2"]


def test_deux_intentions():
    r = RegistreIntentVenue()
    r.lier(intent_id="I1", venue_order_id="v1")
    r.lier(intent_id="I2", venue_order_id="v2")
    assert r.n_positions_distinctes() == 2


def test_intent_de():
    r = RegistreIntentVenue()
    r.lier(intent_id="I1", venue_order_id="v1")
    assert r.intent_de("v1") == "I1"
