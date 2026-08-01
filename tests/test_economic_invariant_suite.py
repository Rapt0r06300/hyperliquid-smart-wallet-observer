"""[ALL #100] economic invariant suite : tests impossibles à contourner sur l'état de simulation."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core import economic_invariant_suite as EIS   # noqa: E402


def test_invariants_unitaires():
    assert EIS.inv_hedge_qty(0.5, 1.0)["ok"] is True and EIS.inv_hedge_qty(1.5, 1.0)["ok"] is False
    assert EIS.inv_reduce_only(2.0, 1.0)["ok"] is True and EIS.inv_reduce_only(1.0, 2.0)["ok"] is False
    assert EIS.inv_fill_unique(["a", "b"])["ok"] is True and EIS.inv_fill_unique(["a", "a"])["ok"] is False
    assert EIS.inv_pnl_sans_fill(5.0, 0)["ok"] is False and EIS.inv_completed_sans_residu("COMPLETED", 0.3)["ok"] is False


def test_suite_agrege_violations():
    etat = {"hedge_qty": 1.5, "actual_fill_qty": 1.0,          # violation
            "fill_ids": ["x", "x"],                            # violation
            "statut": "COMPLETED", "residu": 0.0}              # ok
    r = EIS.verifier_tous(etat)
    assert r["ok"] is False and r["n_violations"] == 2
    noms = {v["invariant"] for v in r["violations"]}
    assert "hedge_qty" in noms and "fill_unique" in noms


def test_etat_sain_aucune_violation():
    etat = {"hedge_qty": 0.5, "actual_fill_qty": 1.0, "fill_ids": ["a", "b"],
            "statut": "COMPLETED", "residu": 0.0, "realized_pnl": 3.0, "n_fills": 2}
    assert EIS.verifier_tous(etat)["ok"] is True
