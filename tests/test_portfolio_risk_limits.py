"""M1 VaR/CVaR + M2 vol targeting."""
from __future__ import annotations

import pytest

from hl_observer.risk.portfolio_risk_limits import var_historique, cvar_historique, facteur_taille_vol


def test_var_et_cvar():
    pnls = [-10.0, -8.0, -5.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0]   # 10 points
    # niveau 90% -> pire 10% = 1 point (le pire = -10) -> VaR 10
    assert var_historique(pnls, niveau=0.9) == pytest.approx(10.0)
    assert cvar_historique(pnls, niveau=0.9) == pytest.approx(10.0)


def test_var_none_si_vide():
    assert var_historique([]) is None and cvar_historique([]) is None


def test_facteur_taille_vol():
    assert facteur_taille_vol(0.02, vol_cible=0.01) == pytest.approx(0.5)   # vol double -> demi-taille
    assert facteur_taille_vol(0.005, vol_cible=0.01, plafond=2.0) == pytest.approx(2.0)  # borne
    assert facteur_taille_vol(0.0, vol_cible=0.01) == 2.0
