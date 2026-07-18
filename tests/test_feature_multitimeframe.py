"""J4 — alignement multi-timeframe sans lookahead."""
from __future__ import annotations

from hl_observer.features.feature_multitimeframe import aligner


def test_utilise_la_derniere_barre_cloturee():
    lente = [(0, 10.0), (60, 20.0), (120, 30.0)]     # barres 1h clôturées
    timeline = [30, 60, 90, 120, 150]
    assert aligner(lente, timeline) == [10.0, 20.0, 20.0, 30.0, 30.0]


def test_none_avant_la_premiere():
    assert aligner([(100, 5.0)], [50, 100, 150]) == [None, 5.0, 5.0]
