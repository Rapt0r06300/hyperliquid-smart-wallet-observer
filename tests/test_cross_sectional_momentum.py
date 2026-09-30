"""I3 — momentum transversal : long les forts, short les faibles, delta-neutre."""
from __future__ import annotations

from hl_observer.signals.cross_sectional_momentum import classer, paniers


def test_classement_decroissant():
    r = classer({"A": 0.05, "B": 0.20, "C": -0.10})
    assert [c for c, _ in r] == ["B", "A", "C"]


def test_paniers_top_bottom():
    rend = {"A": 0.05, "B": 0.20, "C": -0.10, "D": 0.15, "E": -0.30, "F": 0.02}
    p = paniers(rend, k=2)
    assert p["longs"] == ["B", "D"]        # 2 plus forts
    assert p["shorts"] == ["C", "E"] or p["shorts"] == ["E", "C"]   # 2 plus faibles
    assert set(p["shorts"]) == {"E", "C"}


def test_k_borne_a_moitie():
    p = paniers({"A": 1.0, "B": 2.0}, k=5)   # n=2 -> k max = 1
    assert len(p["longs"]) == 1 and len(p["shorts"]) == 1
    assert p["longs"] == ["B"] and p["shorts"] == ["A"]
