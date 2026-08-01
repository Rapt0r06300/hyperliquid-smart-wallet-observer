"""[ALL #93] restart reconciliation : restaurer executors/positions/PnL avant toute nouvelle décision."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.restart_reconciliation import Reconciliateur   # noqa: E402


def test_bloque_avant_reconciliation():
    r = Reconciliateur()
    assert r.peut_decider()["ok"] is False and r.peut_decider()["raison"] == "RECONCILIATION_NON_FAITE"


def test_pret_apres_restauration():
    r = Reconciliateur()
    out = r.restaurer(executors=["ex1"], positions={"BTC": 0.5}, pnl_realise=12.0)
    assert out["n_positions"] == 1 and r.peut_decider()["ok"] is True
    assert r.pnl_realise == 12.0


def test_pnl_invalide_neutre():
    r = Reconciliateur()
    r.restaurer(pnl_realise="NA")
    assert r.pnl_realise == 0.0
