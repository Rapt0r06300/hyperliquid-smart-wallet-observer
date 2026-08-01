"""[ARB lot2 #20] frais recalculés sur fills réconciliés : commission réelle par fill, pas estimée à l'intention."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.fees_model.fee_recompute_reconciled import commission, recomputer   # noqa: E402


def test_commission_unitaire():
    assert commission(1000.0, 5.0) == 0.5                 # 5 bps de 1000
    assert commission(None, 5.0) == "UNMEASURABLE"


def test_somme_fills_reconcilies():
    fills = [{"prix": 100.0, "qte": 1.0, "taux_bps": 5.0}, {"prix": 200.0, "qte": 2.0, "taux_bps": 3.0}]
    r = recomputer(fills)
    # 0.05 + 0.12 = 0.17
    assert r["commission_totale"] == 0.17 and r["n_fills"] == 2


def test_fill_incalculable_non_mesurable():
    r = recomputer([{"prix": 100.0, "qte": 1.0, "taux_bps": None}])
    assert r["commission_totale"] == "UNMEASURABLE"
