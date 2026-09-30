"""[pépite 205] amend-vs-fill race : un fill avant l'acceptation de l'amend s'attribue à l'ancienne version."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.amend_vs_fill_race import resoudre, VERSION_AVANT_AMEND, VERSION_APRES_AMEND, INDETERMINE   # noqa: E402


def test_fill_avant_amend():
    r = resoudre(fill_seq=5, amend_accepte_seq=8)
    assert r["attribution"] == VERSION_AVANT_AMEND


def test_fill_apres_amend():
    r = resoudre(fill_seq=9, amend_accepte_seq=8)
    assert r["attribution"] == VERSION_APRES_AMEND


def test_sequence_manquante():
    assert resoudre(fill_seq=None, amend_accepte_seq=8)["attribution"] == INDETERMINE
