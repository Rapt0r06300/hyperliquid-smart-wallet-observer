"""Tests de l'étiquetage triple-barrière et meta-labeling."""
from __future__ import annotations

from hl_observer.backtesting.labeling import meta_labels, triple_barrier_labels


def test_triple_barrier_directions():
    up = [100.0, 100.2, 100.6, 101.0]           # monte -> TP touché
    down = [100.0, 99.8, 99.4, 99.0]            # descend -> SL touché
    flat = [100.0, 100.05, 100.0, 100.02]      # rien -> 0
    assert triple_barrier_labels(up, [0], tp_bps=40, sl_bps=40, horizon=5) == [1]
    assert triple_barrier_labels(down, [0], tp_bps=40, sl_bps=40, horizon=5) == [-1]
    assert triple_barrier_labels(flat, [0], tp_bps=40, sl_bps=40, horizon=3) == [0]


def test_meta_labels():
    assert meta_labels([1.5, -0.2, 0.0, 3.0]) == [1, 0, 0, 1]
