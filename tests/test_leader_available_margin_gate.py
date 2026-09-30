"""[COPY-VAULT lot2 #55] available-margin gate : différencier une conviction d'un trader à bout de collatéral."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.leader_available_margin_gate import peut_open   # noqa: E402


def test_reserve_suffisante():
    r = peut_open(1000.0, 10000.0, part_min=0.05)        # 10% dispo
    assert r["peut_open"] is True


def test_a_bout_de_collateral():
    r = peut_open(100.0, 10000.0, part_min=0.05)         # 1% dispo
    assert r["peut_open"] is False and r["raison"] == "LEADER_A_BOUT_DE_COLLATERAL"


def test_equity_invalide():
    assert peut_open(100.0, 0.0)["peut_open"] is False
