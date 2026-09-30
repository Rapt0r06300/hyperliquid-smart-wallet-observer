"""[ARB #42] residual timeout : un résidu nu trop vieux -> liquidation paper forcée, quel que soit l'edge."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.residual_timeout import evaluer, CONSERVER, LIQUIDER_PAPER   # noqa: E402


def test_dans_le_ttl_on_conserve():
    r = evaluer(1000.0, 3000.0, ttl_ms=5000.0)
    assert r["action"] == CONSERVER and r["reste_ms"] == 3000.0


def test_trop_vieux_liquide():
    r = evaluer(1000.0, 7000.0, ttl_ms=5000.0)
    assert r["action"] == LIQUIDER_PAPER and r["raison"] == "RESIDU_TROP_VIEUX"


def test_horodatage_inconnu_liquide():
    assert evaluer(None, 7000.0, ttl_ms=5000.0)["action"] == LIQUIDER_PAPER
