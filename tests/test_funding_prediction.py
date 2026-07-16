"""Prédiction du funding pour le carry : prédire, alerter sur l'inversion, refuser si peu d'histo."""
from __future__ import annotations

from hl_observer.funding.funding_prediction import (
    carry_soutenable,
    predire,
    risque_inversion,
)


def test_predire_suit_le_recent_et_refuse_si_peu_d_histo() -> None:
    assert predire([1.0, 1.0]) is None                     # trop court → refus
    # série stable autour de 2.0 → prédiction proche de 2.0
    p = predire([2.0] * 10)
    assert p is not None and abs(p - 2.0) < 1e-6
    # une hausse récente tire la prédiction vers le haut (EWMA pondère le récent)
    p2 = predire([1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 3.0, 3.0, 3.0, 3.0])
    assert p2 is not None and p2 > 2.0


def test_alerte_inversion_quand_le_funding_devient_negatif() -> None:
    # funding positif stable → pas d'alerte
    r = risque_inversion([1.5] * 10)
    assert r is not None and r.alerte is False and r.frac_negatifs == 0.0
    # beaucoup de négatifs (type BERA/STABLE) → alerte
    r2 = risque_inversion([0.2, -0.3, -0.5, -0.4, -0.6, -0.8, -0.83, -0.9])
    assert r2 is not None and r2.alerte is True and r2.frac_negatifs > 0.5
    # historique trop court → None
    assert risque_inversion([1.0, 1.0]) is None


def test_carry_soutenable_exige_funding_positif_couvrant_les_couts_ET_pas_d_inversion() -> None:
    # funding 2.0/h, coût amorti 0.5/h, pas d'inversion → soutenable
    assert carry_soutenable([2.0] * 10, cout_amorti_bps_h=0.5) is True
    # funding sous le coût → NON
    assert carry_soutenable([0.3] * 10, cout_amorti_bps_h=0.5) is False
    # funding qui s'inverse → NON (même si la moyenne semblait ok)
    assert carry_soutenable([0.2, -0.3, -0.5, -0.4, -0.6, -0.8, -0.83, -0.9],
                            cout_amorti_bps_h=0.1) is False
    # pas assez d'historique → None (on ne tranche pas)
    assert carry_soutenable([1.0, 1.0], cout_amorti_bps_h=0.1) is None
