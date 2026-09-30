"""[pépite 206] continuous position reconciliation : position calculée vs report autoritaire."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.continuous_position_reconciliation import reconcilier   # noqa: E402


def test_position_reconciliee():
    assert reconcilier(1.5, 1.5)["coherent"] is True


def test_fill_manque_detecte():
    r = reconcilier(1.5, 2.0)                             # report a 2.0, on calcule 1.5
    assert r["coherent"] is False and r["ecart"] == 0.5 and r["raison"] == "POSITION_LOCALE_DIVERGE_DU_REPORT"


def test_donnee_invalide():
    assert reconcilier(None, 2.0)["coherent"] is False
