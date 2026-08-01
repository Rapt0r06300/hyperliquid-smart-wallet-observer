"""[pépite 207] balance reconciliation : cash/equity du ledger vs reports d'accounting."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.balance_reconciliation import reconcilier   # noqa: E402


def test_balance_reconciliee():
    assert reconcilier(cash_ledger=10000.0, cash_report=10000.005, tolerance_abs=0.01)["coherent"] is True


def test_divergence_cash():
    r = reconcilier(cash_ledger=10000.0, cash_report=9950.0, tolerance_abs=0.01)
    assert r["coherent"] is False and r["ecart"] == -50.0


def test_donnee_invalide():
    assert reconcilier(cash_ledger=None, cash_report=10000.0)["coherent"] is False
