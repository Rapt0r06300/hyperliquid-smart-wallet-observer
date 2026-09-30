"""Tests microstructure avancée."""
from __future__ import annotations

from hl_observer.backtesting.microstructure_extras import (
    adverse_selection_cost,
    hawkes_intensity,
    maker_queue_fill_prob,
)


def test_hawkes_excites_then_decays():
    events = [0.0, 1.0, 2.0]
    near = hawkes_intensity(events, 2.1, mu=0.1, alpha=1.0, beta=1.0)
    far = hawkes_intensity(events, 100.0, mu=0.1, alpha=1.0, beta=1.0)
    assert near > 0.1                              # excité juste après les événements
    assert abs(far - 0.1) < 1e-6                   # retour à l'intensité de base


def test_queue_fill_decreases_with_queue():
    front = maker_queue_fill_prob(0.0, fill_rate=1.0, window=1.0)
    back = maker_queue_fill_prob(100.0, fill_rate=1.0, window=1.0)
    assert 0.0 <= back < front <= 1.0


def test_adverse_cost_grows_with_toxicity():
    assert adverse_selection_cost(0.9) > adverse_selection_cost(0.1)
