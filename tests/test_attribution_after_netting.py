"""[COPY-VAULT #81] attribution after netting : le PnL du trade net reste réparti par vault."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.attribution_after_netting import attribuer   # noqa: E402


def test_repartition_au_prorata_brut():
    # contributions brutes 80 et 20 -> parts 80% / 20% du PnL
    r = attribuer({"vaultA": 80.0, "vaultB": -20.0}, 100.0)
    assert r["parts"]["vaultA"] == 80.0 and r["parts"]["vaultB"] == 20.0
    assert r["controle_somme"] == 100.0


def test_contributions_nulles_non_mesurable():
    assert attribuer({"vaultA": 0.0}, 100.0)["parts"] == "UNMEASURABLE"


def test_pnl_invalide():
    assert attribuer({"vaultA": 80.0}, None)["parts"] == "UNMEASURABLE"
