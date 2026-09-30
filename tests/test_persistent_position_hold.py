"""[ALL #92] persistent PositionHold : exposition survivant à l'arrêt stockée avec sa comptabilité complète."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.persistent_position_hold import StockPositionHold   # noqa: E402


def test_stockage_complet():
    s = StockPositionHold()
    r = s.stocker("BTC", taille=0.5, entry_price=100.0, fees=0.2, realized_pnl=0.0, unrealized_pnl=5.0)
    assert r["ok"] is True
    assert s.charger("BTC")["unrealized_pnl"] == 5.0 and s.lister() == ["BTC"]


def test_hold_incomplet_refuse():
    s = StockPositionHold()
    r = s.stocker("BTC", taille=0.5, entry_price=100.0)   # champs comptables manquants
    assert r["ok"] is False and "fees" in r["manquants"]


def test_coin_absent():
    assert StockPositionHold().charger("XYZ") is None
