"""A4 — funding en z-score : repérer le premium anormalement haut (timing d'entrée) et son évaporation."""
from __future__ import annotations

import pytest

from hl_observer.funding.funding_zscore import MIN_POINTS, zscore_funding


def test_historique_insuffisant_non_fiable():
    z = zscore_funding("HYPE", [0.3] * (MIN_POINTS - 1), 0.9)
    assert z.fiable is False and z.regime == "NON_FIABLE"


def test_spike_detecte_z_positif():
    # historique ~0.2 AVEC variance, courant 1.5 -> z tres positif -> SPIKE
    z = zscore_funding("HYPE", [0.1, 0.2, 0.3] * 16, 1.5)
    assert z.fiable is True and z.zscore > 1.0 and z.regime == "SPIKE"


def test_funding_a_la_moyenne_est_normal():
    z = zscore_funding("HYPE", [0.2] * 24 + [0.4] * 24, 0.3)   # ~moyenne
    assert z.regime == "NORMAL"
    assert abs(z.zscore) < 1.0


def test_premium_evapore_z_negatif():
    # historique eleve ~0.6 AVEC variance, courant retombe a 0.1 -> z tres negatif -> EVAPORE
    z = zscore_funding("HYPE", [0.5, 0.6, 0.7] * 16, 0.1)
    assert z.zscore <= -0.5 and z.regime == "EVAPORE"


def test_courant_par_defaut_est_le_dernier_point():
    z = zscore_funding("HYPE", [0.2] * 47 + [2.0])   # pas de courant -> prend 2.0
    assert z.courant_bps_h == pytest.approx(2.0)
    assert z.regime == "SPIKE"


def test_ecart_type_nul_donne_z_zero():
    z = zscore_funding("HYPE", [0.5] * 48, 0.5)      # tout identique -> sd=0 -> z=0
    assert z.zscore == 0.0 and z.regime == "NORMAL"
