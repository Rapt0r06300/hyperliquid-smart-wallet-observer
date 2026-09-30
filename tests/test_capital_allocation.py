"""Allocation de capital : jamais un centime à une piste perdante ; concentration plafonnée ; cash OK."""
from __future__ import annotations

from hl_observer.risk.capital_allocation import Strategie, allouer


def test_une_piste_a_edge_negatif_recoit_zero() -> None:
    a = allouer([
        Strategie("carry", edge_net_bps=40.0, risque=10.0),
        Strategie("perdante", edge_net_bps=-5.0, risque=10.0),
    ])
    assert "perdante" in a.ecartees
    assert "perdante" not in a.poids
    assert a.poids["carry"] == 0.5             # plafond de concentration (50 %)
    assert a.cash_frac == 0.5                  # le reste reste en cash


def test_le_plafond_de_concentration_est_respecte() -> None:
    a = allouer([
        Strategie("A", edge_net_bps=20.0, risque=10.0),
        Strategie("B", edge_net_bps=20.0, risque=10.0),
    ])
    assert a.poids["A"] == 0.5 and a.poids["B"] == 0.5   # 2×0.5, plafonnées
    assert a.cash_frac == 0.0


def test_plus_d_edge_par_risque_recoit_plus_de_poids() -> None:
    # frac_max relevé pour observer la proportionnalité avant plafond.
    a = allouer(
        [Strategie("gros", edge_net_bps=30.0, risque=10.0),   # score 3
         Strategie("petit", edge_net_bps=10.0, risque=10.0)],  # score 1
        frac_max_par_strat=1.0,
    )
    assert a.poids["gros"] > a.poids["petit"]
    assert abs(a.poids["gros"] - 0.75) < 1e-9
    assert abs(a.poids["petit"] - 0.25) < 1e-9
    assert a.cash_frac == 0.0


def test_aucune_piste_eligible_tout_en_cash() -> None:
    a = allouer([
        Strategie("x", edge_net_bps=0.0, risque=10.0),     # edge non > 0
        Strategie("y", edge_net_bps=5.0, risque=0.0),      # risque nul → écartée
    ])
    assert a.poids == {}
    assert a.cash_frac == 1.0
    assert set(a.ecartees) == {"x", "y"}
