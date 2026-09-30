"""[pépite 217] monotonic order-state version : un vieux PARTIAL retardé ne remplace pas FILLED."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.exec_reconciliation.monotonic_order_state_version import decision, APPLIQUER, IGNORER   # noqa: E402


def test_progression_appliquee():
    assert decision("NEW", "PARTIAL")["action"] == APPLIQUER
    assert decision("PARTIAL", "FILLED")["action"] == APPLIQUER


def test_regression_ignoree():
    r = decision("FILLED", "PARTIAL")                     # vieux partial retardé
    assert r["action"] == IGNORER and r["raison"] == "ETAT_ANTERIEUR_RETARDE"


def test_etat_inconnu_ignore():
    assert decision("FILLED", "BIZARRE")["action"] == IGNORER
