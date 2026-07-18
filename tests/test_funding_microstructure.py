"""Microstructure funding — rang transversal, variance, autocorrélation, saisonnalité."""
from __future__ import annotations

from hl_observer.funding.funding_microstructure import (
    autocorr_lag1, facteur_saisonnier, rang_transversal, variance_funding)


def test_rang_transversal():
    r = rang_transversal({"A": 0.05, "B": 0.30, "C": 0.15})
    assert r["A"] == 0.0 and r["B"] == 1.0 and 0 < r["C"] < 1   # A bas (long), B haut (short)


def test_variance_et_autocorr():
    assert variance_funding([1.0, 1.0]) == 0.0
    assert variance_funding([1.0]) is None
    # série persistante (monte régulièrement) -> autocorr lag1 positive
    assert autocorr_lag1([1.0, 2.0, 3.0, 4.0, 5.0]) > 0
    assert autocorr_lag1([1.0, 1.0]) is None                    # trop court


def test_saisonnier():
    s = facteur_saisonnier(1_700_000_000_000)
    assert "heure_utc" in s and "weekend" in s
