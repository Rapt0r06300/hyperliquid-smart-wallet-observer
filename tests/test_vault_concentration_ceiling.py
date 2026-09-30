"""[COPY-VAULT #83] vault concentration ceiling : un vault ne peut pas absorber tout le budget copy."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.vault_concentration_ceiling import allocation_admissible   # noqa: E402


def test_plafond_part():
    r = allocation_admissible(600.0, budget_total=1000.0, part_max=0.4)
    assert r["alloc"] == 400.0 and r["capee"] is True    # borné a 40% du budget


def test_sous_plafond():
    r = allocation_admissible(300.0, budget_total=1000.0, part_max=0.4)
    assert r["alloc"] == 300.0 and r["capee"] is False


def test_budget_invalide():
    assert allocation_admissible(300.0, budget_total=0.0, part_max=0.4)["refuse"] is True
