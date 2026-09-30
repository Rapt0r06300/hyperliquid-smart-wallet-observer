"""[ARB lot2 #2] amend in-place : modifier sans cancel/recreate préserve la priorité de file quand c'est possible."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.amend_in_place import strategie_modification, AMEND, CANCEL_RECREATE   # noqa: E402


def test_amend_preserve_queue():
    r = strategie_modification(venue_supporte_amend=True, preserve_queue=True)
    assert r["strategie"] == AMEND and r["queue_preservee"] is True


def test_venue_sans_amend():
    r = strategie_modification(venue_supporte_amend=False, preserve_queue=True)
    assert r["strategie"] == CANCEL_RECREATE and r["raison"] == "VENUE_SANS_AMEND"


def test_changement_detruit_queue():
    r = strategie_modification(venue_supporte_amend=True, preserve_queue=False)
    assert r["strategie"] == CANCEL_RECREATE and r["raison"] == "CHANGEMENT_DETRUIT_QUEUE"
