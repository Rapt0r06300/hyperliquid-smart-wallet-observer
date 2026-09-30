"""[ARB lot2 #19] expiration libère budget : le budget réservé est libéré immédiatement à l'expiration."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.expiry_releases_budget import BudgetAvecExpiration   # noqa: E402


def test_reservation_et_liberation_immediate():
    b = BudgetAvecExpiration(1000.0)
    b.reserver("o1", 300.0)
    assert b.disponible() == 700.0
    r = b.expirer("o1")
    assert r["libere"] == 300.0 and r["immediat"] is True and b.disponible() == 1000.0


def test_ordre_inconnu():
    b = BudgetAvecExpiration(1000.0)
    assert b.expirer("zzz")["libere"] == 0.0


def test_reservation_insuffisante_refusee():
    b = BudgetAvecExpiration(100.0)
    assert b.reserver("o1", 200.0)["ok"] is False
