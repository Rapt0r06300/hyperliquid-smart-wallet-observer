"""[COPY-VAULT lot2 #57] deposit/withdrawal detector : variation d'equity hors trading détectée."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.deposit_withdrawal_detector import detecter   # noqa: E402


def test_depot_detecte():
    r = detecter(equity_avant=10000.0, equity_apres=60000.0, pnl_trading=2000.0)
    assert r["detecte"] is True and r["type"] == "DEPOT" and r["montant_inexplique"] == 48000.0


def test_variation_expliquee():
    r = detecter(equity_avant=10000.0, equity_apres=12000.0, pnl_trading=2000.0)
    assert r["detecte"] is False


def test_retrait():
    r = detecter(equity_avant=10000.0, equity_apres=5000.0, pnl_trading=0.0)
    assert r["detecte"] is True and r["type"] == "RETRAIT"
