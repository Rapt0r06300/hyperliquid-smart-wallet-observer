"""[ARB lot2 #13] récupération de submit ambigu : timeout après envoi -> UNKNOWN, jamais REJECTED d'office."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.ambiguous_submit_recovery import traiter_reponse_submit, UNKNOWN, ACKED, REJECTED   # noqa: E402


def test_timeout_reste_unknown():
    r = traiter_reponse_submit(transport_timeout=True, ack_recu=False, client_order_id="c1")
    assert r["statut"] == UNKNOWN and r["a_reconcilier"] is True and r["client_order_id"] == "c1"


def test_ack_recu():
    r = traiter_reponse_submit(transport_timeout=False, ack_recu=True, client_order_id="c1")
    assert r["statut"] == ACKED


def test_rejet_explicite():
    r = traiter_reponse_submit(transport_timeout=False, ack_recu=False, client_order_id="c1")
    assert r["statut"] == REJECTED
