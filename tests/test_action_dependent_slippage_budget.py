"""[COPY-VAULT #75] action-dependent slippage budget : OPEN strict, CLOSE plus tolérant."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.copy_vault.action_dependent_slippage_budget import budget_slippage_bps, acceptable   # noqa: E402


def test_budget_selon_action():
    assert budget_slippage_bps("OPEN", budget_open_bps=8.0, budget_close_bps=25.0) == 8.0
    assert budget_slippage_bps("CLOSE", budget_open_bps=8.0, budget_close_bps=25.0) == 25.0
    assert budget_slippage_bps("???") == 8.0             # inconnu = strict


def test_close_accepte_plus_de_cout():
    # 20 bps refusé a l'ouverture mais accepté a la fermeture
    assert acceptable(20.0, "OPEN", budget_open_bps=8.0, budget_close_bps=25.0)["acceptable"] is False
    assert acceptable(20.0, "CLOSE", budget_open_bps=8.0, budget_close_bps=25.0)["acceptable"] is True


def test_slippage_inconnu_refuse():
    assert acceptable(None, "CLOSE")["acceptable"] is False


def test_valeurs_non_finies_ou_booleennes_refusees():
    assert acceptable(float("nan"), "OPEN")["raison"] == "SLIPPAGE_INCONNU"
    assert acceptable(float("inf"), "CLOSE")["raison"] == "SLIPPAGE_INCONNU"
    assert acceptable(True, "OPEN")["raison"] == "SLIPPAGE_INCONNU"


def test_budget_negatif_ou_non_fini_refuse_l_action():
    assert budget_slippage_bps("OPEN", budget_open_bps=-1.0) is None
    assert budget_slippage_bps("CLOSE", budget_close_bps=float("nan")) is None
    assert acceptable(0.0, "OPEN", budget_open_bps=-1.0)["raison"] == "BUDGET_INVALIDE"


def test_slippage_negative_refusee():
    assert acceptable(-0.1, "CLOSE")["raison"] == "SLIPPAGE_INCONNU"
