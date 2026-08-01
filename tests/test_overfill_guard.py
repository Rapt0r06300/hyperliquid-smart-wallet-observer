"""[pépite 201] overfill guard : filled > requested détecté, overfill isolé, jamais absorbé en silence."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.overfill_guard import verifier   # noqa: E402


def test_overfill_detecte():
    r = verifier(1.2, 1.0)
    assert r["overfill"] is True and r["overfill_qty"] == 0.2


def test_pas_dloverfill():
    r = verifier(0.8, 1.0)
    assert r["overfill"] is False and r["overfill_qty"] == 0.0


def test_quantite_invalide():
    assert verifier(None, 1.0)["overfill"] is True
