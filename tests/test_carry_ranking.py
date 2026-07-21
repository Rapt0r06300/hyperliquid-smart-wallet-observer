"""Classement du carry : ranger les MEILLEURS coins, écarter les non soutenables. Deny-by-default."""
from __future__ import annotations

from hl_observer.strategies.carry_ranking import classer, meilleur


def test_classe_par_carry_net_decroissant() -> None:
    fundings = {
        "HAUT": [3.0] * 12,     # funding élevé et stable
        "BAS": [1.0] * 12,      # positif mais plus bas
    }
    cl = classer(fundings, cout_amorti_bps_h=0.5)
    assert [c.coin for c in cl] == ["HAUT", "BAS"]
    assert cl[0].rang == 1 and cl[1].rang == 2
    assert cl[0].net_bps_h > cl[1].net_bps_h
    assert abs(cl[0].net_bps_h - 2.5) < 1e-9    # 3.0 − 0.5


def test_ecarte_les_non_soutenables_et_les_menaces_d_inversion() -> None:
    fundings = {
        "OK": [2.0] * 12,
        "SOUS_COUT": [0.2] * 12,                                  # funding < coûts → écarté
        "INVERSION": [0.2, -0.3, -0.5, -0.4, -0.6, -0.8, -0.83, -0.9],  # s'inverse → écarté
        "COURT": [5.0, 5.0],                                      # histo trop court → écarté
    }
    cl = classer(fundings, cout_amorti_bps_h=0.5)
    assert [c.coin for c in cl] == ["OK"]


def test_meilleur_renvoie_le_haut_du_panier_ou_None() -> None:
    m = meilleur({"A": [4.0] * 12, "B": [1.5] * 12}, cout_amorti_bps_h=0.5)
    assert m is not None and m.coin == "A"
    # aucun soutenable → None (on n'invente pas un gagnant)
    assert meilleur({"X": [0.1] * 12}, cout_amorti_bps_h=0.5) is None
