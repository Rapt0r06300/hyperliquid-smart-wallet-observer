"""[COPY-VAULT #78] target-exposure reconciliation : comparer exposure cible vs paper, calculer l'ajustement."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.target_exposure_reconciliation import reconcilier   # noqa: E402


def test_aligne():
    r = reconcilier(1.0, 1.0)
    assert r["aligne"] is True and r["ajustement"] == 0.0


def test_derive_a_corriger():
    r = reconcilier(1.0, 0.7)
    assert r["aligne"] is False and r["ajustement"] == 0.3 and r["sens"] == "ACHAT"


def test_manquant_non_mesurable():
    assert reconcilier(1.0, None)["ajustement"] == "UNMEASURABLE"
