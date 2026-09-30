"""[ALL #88] central BudgetChecker : capital réservé au niveau exécution, une seule source de vérité."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.central_budget_checker import BudgetCentral   # noqa: E402


def test_reservation_centrale():
    b = BudgetCentral(1000.0)
    assert b.reserver("s1", 400.0)["ok"] is True
    assert b.disponible() == 600.0


def test_sur_engagement_refuse():
    b = BudgetCentral(1000.0)
    b.reserver("s1", 700.0)
    r = b.reserver("s2", 400.0)                           # 700+400 > 1000
    assert r["ok"] is False and r["raison"] == "BUDGET_INSUFFISANT"


def test_liberation():
    b = BudgetCentral(1000.0)
    b.reserver("s1", 400.0)
    assert b.liberer("s1") is True and b.disponible() == 1000.0
