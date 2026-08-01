"""[lot2 #94] virtual subaccounts : budgets isolés par module, consolidation = somme."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.virtual_subaccounts import SousComptesVirtuels   # noqa: E402


def test_isolation():
    s = SousComptesVirtuels()
    s.crediter("cross_venue", 1000.0)
    s.crediter("copy_vault", 500.0)
    assert s.peut_depenser("cross_venue", 800.0)["ok"] is True
    assert s.peut_depenser("copy_vault", 800.0)["ok"] is False   # ne touche pas au budget de l'autre


def test_consolidation():
    s = SousComptesVirtuels()
    s.crediter("a", 1000.0)
    s.crediter("b", 500.0)
    assert s.consolider() == 1500.0


def test_montant_invalide():
    assert SousComptesVirtuels().peut_depenser("a", -1.0)["ok"] is False
