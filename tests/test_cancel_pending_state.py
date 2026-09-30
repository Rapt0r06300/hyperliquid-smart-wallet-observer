"""[ARB lot2 #12] état CANCEL_PENDING bloquant : pas de nouvelle quote contradictoire avant résolution."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.cancel_pending_state import EtatCancelPending   # noqa: E402


def test_bloque_pendant_cancel():
    e = EtatCancelPending()
    e.marquer_cancel_pending("BTC", "BUY")
    r = e.peut_poser("BTC", "BUY")
    assert r["peut_poser"] is False and r["raison"] == "CANCEL_PENDING_BLOQUANT"


def test_debloque_apres_resolution():
    e = EtatCancelPending()
    e.marquer_cancel_pending("BTC", "BUY")
    e.resoudre("BTC", "BUY")
    assert e.peut_poser("BTC", "BUY")["peut_poser"] is True


def test_autre_cle_non_bloquee():
    e = EtatCancelPending()
    e.marquer_cancel_pending("BTC", "BUY")
    assert e.peut_poser("BTC", "SELL")["peut_poser"] is True   # autre côté libre
