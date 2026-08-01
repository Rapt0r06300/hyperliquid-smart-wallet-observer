"""[pépite 230] linear/inverse contract normalization : notional/PnL unifiés en USD."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.arbitrage.linear_inverse_normalization import notional_usd, pnl_usd, LINEAIRE, INVERSE   # noqa: E402


def test_notional_lineaire():
    assert notional_usd(2.0, 100.0, type_contrat=LINEAIRE) == 200.0


def test_pnl_inverse_non_lineaire():
    # inverse : qty*cs*(1/entree - 1/sortie) ; long qui monte de 100 a 125 -> gain
    r = pnl_usd(100.0, 100.0, 125.0, type_contrat=INVERSE)
    assert r == round(100.0 * (1/100.0 - 1/125.0), 8) and r > 0


def test_prix_invalide():
    assert notional_usd(2.0, 0.0, type_contrat=LINEAIRE) == "UNMEASURABLE"
