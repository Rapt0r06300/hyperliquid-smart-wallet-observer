"""J2/J3 — normalisation causale + outliers + manquants."""
from __future__ import annotations

import pytest

from hl_observer.features.feature_normalize import zscore_roulant, clamp_outliers, combler_manquants


def test_zscore_warmup_none_puis_causal():
    z = zscore_roulant([1.0, 2.0, 3.0], fenetre=20)
    assert z[0] is None                    # 1 point -> warmup
    assert z[-1] is not None and z[-1] > 0 # dernier au-dessus de sa moyenne causale


def test_clamp_ecrete_un_spike():
    serie = [1.0, 2.0, 1.5, 2.5, 2.0, 100.0]     # historique AVEC variance, puis spike
    out = clamp_outliers(serie, k_sigma=3.0, fenetre=50)
    assert out[-1] < 100.0                 # le spike est ecrete sur la distribution PASSEE
    assert out[0] == 1.0


def test_combler_forward_fill():
    assert combler_manquants([1.0, None, 2.0, None]) == [1.0, 1.0, 2.0, 2.0]


def test_combler_trop_de_trous_none():
    assert combler_manquants([1.0, None, None, None, None], max_trous_consecutifs=3) is None
