"""N1/N2/N3 — allocation inverse-vol, rebalancement cost-aware, capacité."""
from __future__ import annotations

import pytest

from hl_observer.risk.allocator import poids_inverse_vol, rebalancement_necessaire, capacite_max_usd


def test_inverse_vol_donne_plus_au_moins_volatil():
    w = poids_inverse_vol({"A": 0.01, "B": 0.02})   # A moitie moins volatil -> 2x plus de poids
    assert w["A"] == pytest.approx(2 / 3) and w["B"] == pytest.approx(1 / 3)
    assert sum(w.values()) == pytest.approx(1.0)


def test_vol_nulle_exclue():
    assert "Z" not in poids_inverse_vol({"A": 0.01, "Z": 0.0})


def test_rebalancement_bande():
    assert rebalancement_necessaire({"A": 0.5}, {"A": 0.52}, bande=0.05) is False   # ecart < bande
    assert rebalancement_necessaire({"A": 0.5}, {"A": 0.7}, bande=0.05) is True


def test_capacite():
    # profondeur 100k, impact 2%, securite 5 -> 400$
    assert capacite_max_usd(100_000.0, impact_max_frac=0.02, securite=5.0) == pytest.approx(400.0)
