"""[ARB #15] hedge reserve : une réserve d'unwind ne peut jamais servir à ouvrir une nouvelle position."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.hedge_reserve import ReserveHedge   # noqa: E402


def test_ouverture_ne_touche_pas_la_reserve():
    rh = ReserveHedge(1000.0, reserve_unwind_usd=200.0)
    assert rh.capital_ouvrable() == 800.0
    assert rh.peut_ouvrir(800.0)["ok"] is True
    assert rh.peut_ouvrir(801.0)["ok"] is False                 # empiéterait sur la réserve


def test_ouvrir_consomme_seulement_louvrable():
    rh = ReserveHedge(1000.0, reserve_unwind_usd=200.0)
    assert rh.ouvrir(500.0) is True
    assert rh.capital_ouvrable() == 300.0
    assert rh.ouvrir(400.0) is False                            # 400 > 300 ouvrable restant


def test_reserve_sert_uniquement_a_deboucler():
    rh = ReserveHedge(1000.0, reserve_unwind_usd=200.0)
    r = rh.utiliser_pour_unwind(250.0)
    assert r["pris"] == 200.0 and r["refuse"] == 50.0           # bornée à la réserve
