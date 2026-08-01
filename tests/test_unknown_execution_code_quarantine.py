"""[pépite 218] unknown execution code = quarantine : code inconnu -> UNKNOWN_SOURCE_STATE, aucune supposition."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.unknown_execution_code_quarantine import classifier, UNKNOWN_SOURCE_STATE   # noqa: E402


def test_code_connu():
    r = classifier("FILLED")
    assert r["reconnu"] is True and r["quarantaine"] is False


def test_code_inconnu_quarantaine():
    r = classifier("WEIRD_STATUS_42")
    assert r["statut"] == UNKNOWN_SOURCE_STATE and r["quarantaine"] is True


def test_casse_indifferente():
    assert classifier("filled")["reconnu"] is True
