"""[pépite 249] dust inventory ledger : les résidus sous minimum ne disparaissent jamais des comptes."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.order_lifecycle.dust_inventory_ledger import LedgerDust   # noqa: E402


def test_dust_conserve():
    led = LedgerDust()
    led.ajouter("BTC", 0.0001)
    led.ajouter("BTC", 0.0002)
    assert led.dust("BTC") == 0.0003


def test_qte_invalide():
    assert LedgerDust().ajouter("BTC", None)["ok"] is False


def test_total_coins():
    led = LedgerDust()
    led.ajouter("BTC", 0.001)
    led.ajouter("ETH", 0.002)
    assert led.total_coins() == 2
