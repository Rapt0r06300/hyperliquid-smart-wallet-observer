"""[pépite 204] cancel-vs-fill race : résolution causale par séquence, pas par ordre d'arrivée."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.cancel_vs_fill_race import resoudre, FILL_PUIS_CANCEL, CANCEL_PUIS_FILL, INDETERMINE   # noqa: E402


def test_fill_avant_cancel():
    r = resoudre(fill_seq=5, cancel_seq=8)
    assert r["resolution"] == FILL_PUIS_CANCEL


def test_fill_apres_cancel_a_reconcilier():
    r = resoudre(fill_seq=8, cancel_seq=5)
    assert r["resolution"] == CANCEL_PUIS_FILL and r["a_reconcilier"] is True


def test_indetermine():
    assert resoudre(fill_seq=5, cancel_seq=5)["resolution"] == INDETERMINE
    assert resoudre(fill_seq=None, cancel_seq=5)["resolution"] == INDETERMINE
