"""H2 — alpha résiduel : un leader qui n'est QUE du béta-BTC a un alpha ~0 (il suit, il ne prédit pas)."""
from __future__ import annotations

import pytest

from hl_observer.backtesting.residual_alpha import beta_btc, alpha_residuel, a_de_l_alpha

BTC = [1.0, -2.0, 3.0, -1.0, 2.0, -3.0, 1.5, -0.5, 2.5, -1.5] * 3   # 30 points, avec variance


def test_pur_beta_btc_pas_d_alpha():
    strat = [2.0 * x for x in BTC]                      # juste 2x BTC -> aucun edge propre
    assert beta_btc(strat, BTC) == pytest.approx(2.0)
    assert alpha_residuel(strat, BTC) == pytest.approx(0.0, abs=1e-9)
    assert a_de_l_alpha(strat, BTC) is False            # suit BTC, ne predit pas -> rejete


def test_vrai_alpha_est_isole():
    strat = [0.5 * x + 3.0 for x in BTC]                # 0.5x BTC + edge constant +3
    assert beta_btc(strat, BTC) == pytest.approx(0.5)
    assert alpha_residuel(strat, BTC) == pytest.approx(3.0)
    assert a_de_l_alpha(strat, BTC) is True             # vrai edge apres neutralisation BTC


def test_deny_by_default_trop_peu_de_points():
    assert beta_btc([1.0, 2.0], [1.0, 2.0]) is None
    assert a_de_l_alpha([1.0, 2.0], [1.0, 2.0]) is False


def test_btc_constant_non_mesurable():
    assert beta_btc([1.0] * 30, [5.0] * 30) is None     # BTC sans variance -> pas de beta
