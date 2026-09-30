"""A1 — persistance du funding : le carry doit décider sur le funding TENU, pas sur un spike fugace."""
from __future__ import annotations

import pytest

from hl_observer.funding.funding_persistence import (
    PLANCHER_PROTOCOLAIRE_BPS_H as PLANCHER, MIN_POINTS,
    estimer_persistance, couvre_cout,
)


def test_historique_insuffisant_non_fiable():
    fp = estimer_persistance("HYPE", [0.3] * (MIN_POINTS - 1))
    assert fp.fiable is False and fp.motif == "HISTORIQUE_INSUFFISANT"
    assert couvre_cout(fp, cout_entree_bps=1.0, horizon_h=100) is False   # deny-by-default


def test_serie_vide_non_fiable():
    assert estimer_persistance("HYPE", []).fiable is False
    assert estimer_persistance("HYPE", None).fiable is False


def test_un_spike_fugace_ne_gonfle_PAS_le_funding_persistant():
    # 40h au plancher + 1 pic énorme -> le persistant doit rester ~plancher (on ignore le pic)
    serie = [PLANCHER] * 40 + [5.0]
    fp = estimer_persistance("SPIKE", serie)
    assert fp.fiable is True
    assert fp.funding_persistant_bps_h == pytest.approx(PLANCHER, abs=1e-6)  # PAS gonflé par le pic
    moyenne = sum(serie) / len(serie)
    assert fp.funding_persistant_bps_h < moyenne                             # + prudent que la moyenne
    assert fp.funding_median_bps_h == pytest.approx(PLANCHER)


def test_premium_reellement_persistant_est_compte():
    # funding stable à 0.5 -> premium 0.375 tenu tout le temps -> persistant = 0.5
    fp = estimer_persistance("STABLE", [0.5] * 48)
    assert fp.funding_persistant_bps_h == pytest.approx(0.5, abs=1e-6)
    assert fp.premium_persistant_bps_h == pytest.approx(0.5 - PLANCHER, abs=1e-6)
    assert fp.part_du_temps_au_dessus_plancher == pytest.approx(1.0)


def test_part_du_temps_et_volatilite():
    serie = [PLANCHER] * 24 + [0.4] * 24                 # moitié plancher, moitié au-dessus
    fp = estimer_persistance("MIX", serie)
    assert fp.part_du_temps_au_dessus_plancher == pytest.approx(0.5)
    assert fp.volatilite_bps_h > 0.0


def test_couvre_cout_utilise_le_persistant_pas_le_pic():
    # pic fugace : le persistant (~plancher 0.125) ne couvre PAS un coût de 9 bps en 24h
    fp_spike = estimer_persistance("SPIKE", [PLANCHER] * 40 + [50.0])
    assert couvre_cout(fp_spike, cout_entree_bps=9.0, horizon_h=24) is False
    # funding vraiment persistant à 0.5 : 0.5*24 = 12 bps >= 9 -> couvre
    fp_ok = estimer_persistance("STABLE", [0.5] * 48)
    assert couvre_cout(fp_ok, cout_entree_bps=9.0, horizon_h=24) is True
