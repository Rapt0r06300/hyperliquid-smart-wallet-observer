"""Tests de la validation croisée avancée."""
from __future__ import annotations

from hl_observer.backtesting.cross_validation import (
    combinatorial_purged_splits,
    purged_walk_forward_splits,
    whites_reality_check,
)


def test_walk_forward_is_causal_with_embargo():
    splits = purged_walk_forward_splits(100, n_splits=5, embargo=5)
    assert len(splits) == 5
    assert splits[0][0] == []                       # 1er fold : pas de passé
    tr, te = splits[2]
    assert max(tr) < min(te) - 5 + 1                # embargo respecté, train strictement avant test


def test_cpcv_covers_and_disjoint():
    splits = combinatorial_purged_splits(5, 2)
    assert len(splits) == 10                        # C(5,2)
    for train, test in splits:
        assert set(train).isdisjoint(test)
        assert set(train) | set(test) == set(range(5))


def test_reality_check_significance():
    strong = whites_reality_check([1.0] * 100, [0.0] * 100)   # domination nette
    none = whites_reality_check([0.0] * 100, [0.0] * 100)     # aucun edge
    assert strong < 0.05
    assert none > 0.5
