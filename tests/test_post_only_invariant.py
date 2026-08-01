"""[CROSS-VENUE lot2 #8] post-only invariant : un maker qui croiserait le spread est rejeté, jamais compté maker."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.post_only_invariant import verifier, ACCEPTE, REJETE   # noqa: E402


def test_buy_reste_maker():
    r = verifier(99.9, 100.0, "ACHAT")                   # achat sous l'ask -> maker
    assert r["decision"] == ACCEPTE and r["maker"] is True


def test_buy_croise_rejete():
    r = verifier(100.0, 100.0, "ACHAT")                  # achat au niveau de l'ask -> croiserait
    assert r["decision"] == REJETE and r["maker"] is False and r["raison"] == "CROISERAIT_LE_SPREAD_REPRICER"


def test_sell_croise_rejete():
    r = verifier(50.0, 50.0, "VENTE")                    # vente au niveau du bid -> croiserait
    assert r["decision"] == REJETE
    assert verifier(50.1, 50.0, "VENTE")["decision"] == ACCEPTE
