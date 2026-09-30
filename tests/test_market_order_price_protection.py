"""[pépite 225] market-order price protection : une jambe urgente reçoit un prix borné, pas un sweep."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.market_order_price_protection import prix_limite_protege, remplissable   # noqa: E402


def test_achat_plafonne():
    r = prix_limite_protege(100.0, "ACHAT", tolerance_bps=50.0)
    assert r["ok"] is True and r["prix_max"] == 100.5


def test_remplissable_borne():
    assert remplissable(100.3, sens="ACHAT", borne=100.5) is True
    assert remplissable(100.7, sens="ACHAT", borne=100.5) is False   # au-dela = pas rempli (sweep evite)


def test_prix_invalide():
    assert prix_limite_protege(0.0, "ACHAT")["ok"] is False
