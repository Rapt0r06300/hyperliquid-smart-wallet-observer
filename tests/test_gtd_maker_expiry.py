"""[CROSS-VENUE lot2 #7] GTD maker expiry : une quote maker au-delà de son TTL expire et doit être annulée."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.gtd_maker_expiry import etat_quote, VALIDE, EXPIREE   # noqa: E402


def test_valide_dans_ttl():
    r = etat_quote(1000.0, 3000.0, ttl_ms=5000.0)
    assert r["etat"] == VALIDE and r["reste_ms"] == 3000.0


def test_expiree_hors_ttl():
    r = etat_quote(1000.0, 7000.0, ttl_ms=5000.0)
    assert r["etat"] == EXPIREE and r["a_annuler"] is True


def test_horodatage_inconnu_expiree():
    assert etat_quote(None, 7000.0, ttl_ms=5000.0)["etat"] == EXPIREE
