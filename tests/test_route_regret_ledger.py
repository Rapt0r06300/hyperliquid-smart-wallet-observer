"""[pépite 242] route-regret ledger : PnL obtenu vs meilleure route disponible à la décision."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.routing.route_regret_ledger import RegretLedger   # noqa: E402


def test_regret_positif():
    led = RegretLedger()
    led.enregistrer(pnl_realise=8.0, pnl_meilleure_route_dispo=10.0)
    assert led.resume()["regret_total"] == 2.0


def test_regret_borne_a_zero():
    led = RegretLedger()
    led.enregistrer(pnl_realise=12.0, pnl_meilleure_route_dispo=10.0)   # on a fait mieux -> regret 0
    assert led.resume()["regret_total"] == 0.0


def test_pnl_invalide():
    led = RegretLedger()
    assert led.enregistrer(pnl_realise=None, pnl_meilleure_route_dispo=10.0)["ok"] is False
