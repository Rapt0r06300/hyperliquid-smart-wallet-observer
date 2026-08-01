"""[ARB lot2 #14] cancel différé : ordre au statut inconnu sans id venue -> différer jusqu'à réconciliation."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.deferred_cancel_unknown import decision_cancel, ANNULER, DIFFERER   # noqa: E402


def test_unknown_sans_id_differe():
    r = decision_cancel(statut="UNKNOWN", venue_order_id=None)
    assert r["action"] == DIFFERER and r["raison"] == "STATUT_INCONNU_SANS_ID_VENUE"


def test_id_connu_annule():
    r = decision_cancel(statut="OPEN", venue_order_id="v123")
    assert r["action"] == ANNULER


def test_id_manquant_differe():
    assert decision_cancel(statut="OPEN", venue_order_id="")["action"] == DIFFERER
