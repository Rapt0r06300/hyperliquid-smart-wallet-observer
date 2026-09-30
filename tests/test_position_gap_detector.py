"""[COPY-VAULT lot2 #38] gap detector basé position : fills n'expliquant pas la position -> gap."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.position_gap_detector import detecter   # noqa: E402


def test_position_expliquee():
    r = detecter(1.0, [0.5, -0.2], 1.3)                  # 1 + 0.3 = 1.3
    assert r["gap"] is False


def test_gap_sans_erreur_reseau():
    r = detecter(1.0, [0.5], 2.0)                        # 1 + 0.5 = 1.5 != 2.0
    assert r["gap"] is True and r["raison"] == "FILLS_N_EXPLIQUENT_PAS_LA_POSITION"


def test_donnee_invalide():
    assert detecter(1.0, [None], 1.5)["gap"] is True
