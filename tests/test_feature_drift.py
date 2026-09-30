"""J6 — moniteur de drift : alerter quand la distribution change."""
from __future__ import annotations

from hl_observer.features.feature_drift import drift


def test_pas_de_drift_meme_distribution():
    ref = [1.0, 2.0, 3.0, 2.0, 1.0, 2.0, 3.0, 2.0]
    rec = [2.0, 1.0, 3.0, 2.0, 1.0, 3.0, 2.0, 2.0]
    d = drift(ref, rec)
    assert d["drift_detecte"] is False


def test_drift_decalage_de_moyenne():
    ref = [0.0, 1.0, -1.0, 0.0, 1.0, -1.0]
    rec = [10.0, 11.0, 9.0, 10.0, 11.0, 9.0]         # moyenne bien plus haute
    assert drift(ref, rec)["drift_detecte"] is True


def test_drift_explosion_de_vol():
    ref = [1.0, 1.0, 1.0, 1.0, 1.1, 0.9]
    rec = [1.0, 50.0, -40.0, 30.0, -20.0, 10.0]      # vol qui explose
    assert drift(ref, rec)["drift_detecte"] is True


def test_non_mesurable_trop_peu():
    assert drift([1.0], [2.0]) is None
