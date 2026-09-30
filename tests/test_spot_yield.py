"""A6 — jambe spot productive : rendement compte SEULEMENT si dispo ET tenu jusqu'a maturite."""
from __future__ import annotations

import pytest

from hl_observer.funding.spot_yield import (
    APY_HYPE_STAKING, apy_vers_bps_h, rendement_spot_bps_h,
)


def test_conversion_apy_vers_bps_h():
    # 2,3 %/an ≈ 0,0263 bps/h
    assert apy_vers_bps_h(0.023) == pytest.approx(0.023 / (365 * 24) * 1e4, rel=1e-6)
    assert apy_vers_bps_h(APY_HYPE_STAKING) > 0.0


def test_off_par_defaut_deny_by_default():
    assert rendement_spot_bps_h(APY_HYPE_STAKING) == 0.0                         # dispo=False par defaut


def test_off_si_pas_tenu_jusqu_a_maturite():
    # dispo mais carry exit-rapide -> 0 (le delai d'unstaking casserait la sortie)
    assert rendement_spot_bps_h(APY_HYPE_STAKING, disponible=True, tenu_jusqu_a_maturite=False) == 0.0


def test_compte_seulement_si_dispo_ET_maturite():
    r = rendement_spot_bps_h(APY_HYPE_STAKING, disponible=True, tenu_jusqu_a_maturite=True)
    assert r == pytest.approx(apy_vers_bps_h(APY_HYPE_STAKING), abs=1e-5)   # arrondi 6 decimales
    assert r > 0.0


def test_apy_nul_ou_negatif_donne_zero():
    assert rendement_spot_bps_h(0.0, disponible=True, tenu_jusqu_a_maturite=True) == 0.0
    assert rendement_spot_bps_h(-0.01, disponible=True, tenu_jusqu_a_maturite=True) == 0.0
