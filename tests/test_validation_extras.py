"""Tests validation supplémentaire."""
from __future__ import annotations

from hl_observer.backtesting.validation_extras import (
    regime_split_indices,
    walk_forward_multi_window,
)


def test_walk_forward_windows_are_causal():
    splits = walk_forward_multi_window(100, train_size=30, test_size=10, step=10)
    assert len(splits) == 7
    for train, test in splits:
        assert len(train) == 30 and len(test) == 10
        assert max(train) < min(test)


def test_regime_split_separates():
    returns = [0.001] * 30 + [0.05] * 30
    d = regime_split_indices(returns)
    assert sum(1 for i in d["calm"] if i < 30) >= 27       # calme surtout au début
    assert sum(1 for i in d["volatile"] if i >= 30) >= 27  # volatil surtout à la fin
