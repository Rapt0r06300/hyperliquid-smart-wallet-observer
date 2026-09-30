"""[CABLAGE étage B] copy_stage : fill leader → intention de copie mise à l'échelle de notre equity."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.copy_stage import intent_copie   # noqa: E402


def test_mise_a_echelle_et_notional_signe():
    ev = {"coin": "BTC", "px": 60000.0, "sz": 1.0, "signe": 1}
    r = intent_copie(ev, notre_equity=1000.0, leader_equity=100000.0)   # ratio 0.01 -> qty 0.01 -> 600$
    assert r["refuse"] is False and r["qty"] == 0.01 and r["intent"]["montant_signe"] == 600.0
    assert r["intent"]["venue"] == "HYPERLIQUID" and r["intent"]["coin"] == "BTC"


def test_sens_vente_notional_negatif():
    ev = {"coin": "ETH", "px": 3000.0, "sz": 2.0, "signe": -1}
    r = intent_copie(ev, notre_equity=1000.0, leader_equity=100000.0)   # ratio 0.01 -> qty 0.02 -> -60$
    assert r["intent"]["montant_signe"] == -60.0 and r["side"] == "SELL"


def test_equity_leader_invalide_refuse():
    ev = {"coin": "BTC", "px": 60000.0, "sz": 1.0, "signe": 1}
    assert intent_copie(ev, notre_equity=1000.0, leader_equity=0.0)["refuse"] is True


def test_sens_absent_refuse_sans_intention():
    ev = {"coin": "BTC", "px": 60000.0, "sz": 1.0, "signe": 0}
    r = intent_copie(ev, notre_equity=1000.0, leader_equity=100000.0)
    assert r == {"refuse": True, "raison": "SENS_ABSENT"}
    assert "intent" not in r
