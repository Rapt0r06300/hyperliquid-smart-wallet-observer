"""[lot2 #85] queue-value engine : AMEND/CANCEL_REPLACE/HOLD selon valeur de file vs bénéfice du reprix."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.quoting.queue_value_engine import decider, AMEND, CANCEL_REPLACE, HOLD   # noqa: E402


def test_hold_si_queue_vaut_plus():
    r = decider(valeur_queue=10.0, benefice_nouveau_prix=5.0)
    assert r["decision"] == HOLD


def test_amend_si_venue_supporte():
    r = decider(valeur_queue=2.0, benefice_nouveau_prix=10.0, venue_supporte_amend=True)
    assert r["decision"] == AMEND


def test_cancel_replace_sans_amend():
    r = decider(valeur_queue=2.0, benefice_nouveau_prix=10.0, cout_cancel=1.0, venue_supporte_amend=False)
    assert r["decision"] == CANCEL_REPLACE
    assert decider(valeur_queue=None, benefice_nouveau_prix=10.0)["decision"] == "UNMEASURABLE"
