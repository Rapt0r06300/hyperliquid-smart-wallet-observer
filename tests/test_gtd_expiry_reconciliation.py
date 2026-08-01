"""[pépite 223] GTD expiry reconciliation : bonne clé + budget libéré + ordre retiré."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.gtd_expiry_reconciliation import reconcilier_expiration   # noqa: E402


def test_reconciliation_complete():
    r = reconcilier_expiration(order_id="o1", client_order_id="c1", instrument="BTC",
                               budget_libere=True, ordre_retire=True)
    assert r["reconcilie"] is True


def test_budget_non_libere():
    r = reconcilier_expiration(order_id="o1", client_order_id="c1", instrument="BTC",
                               budget_libere=False, ordre_retire=True)
    assert r["reconcilie"] is False and "BUDGET_NON_LIBERE" in r["manques"]


def test_cle_incomplete():
    r = reconcilier_expiration(order_id="o1", client_order_id=None, instrument="BTC",
                               budget_libere=True, ordre_retire=True)
    assert "CLE_INCOMPLETE" in r["manques"]
