"""Découpage d'ordre : à 500 $ c'est un non-sujet ; sinon il n'aide QUE si le carnet se recharge."""
from __future__ import annotations

from hl_observer.backtesting.order_split_benefit import evaluer_decoupage


def test_a_500usd_l_impact_est_negligeable_donc_le_decoupage_est_inutile() -> None:
    # 500 $ dans un carnet de 50 000 $ → impact ≈ 0,5 bps (< 1) → ce n'est pas le combat.
    v = evaluer_decoupage(500.0, 50_000.0, n_tranches=4)
    assert v.impact_unique_bps is not None and v.impact_unique_bps < 1.0
    assert v.aide is False
    assert v.motif == "IMPACT_NEGLIGEABLE_A_CE_NOTIONAL"


def test_sur_un_carnet_statique_le_decoupage_n_aide_pas() -> None:
    # gros ordre (impact > 1 bps), mais AUCUNE liquidité fraîche → découper n'aide pas.
    v = evaluer_decoupage(5_000.0, 50_000.0, n_tranches=4, liquidite_fraiche_par_tranche=0.0)
    assert v.impact_unique_bps is not None and v.impact_unique_bps >= 1.0
    assert v.aide is False
    assert v.motif == "CARNET_STATIQUE_LE_DECOUPAGE_N_AIDE_PAS"


def test_avec_liquidite_fraiche_le_decoupage_reduit_l_impact() -> None:
    v = evaluer_decoupage(5_000.0, 50_000.0, n_tranches=4, liquidite_fraiche_par_tranche=20_000.0)
    assert v.gain_bps is not None and v.gain_bps > 0.5
    assert v.aide is True
    assert v.motif == "LE_DECOUPAGE_AIDE_GRACE_A_LA_LIQUIDITE_FRAICHE"


def test_profondeur_inconnue_ne_ment_pas() -> None:
    v = evaluer_decoupage(500.0, 0.0, n_tranches=4)
    assert v.impact_unique_bps is None
    assert v.aide is False
    assert v.motif == "PROFONDEUR_INCONNUE"
