"""Tests des diagnostics ML."""
from __future__ import annotations

from hl_observer.backtesting.ml_diagnostics import (
    ks_statistic,
    pca_first_component,
    permutation_importance,
)


def test_permutation_importance_flags_informative_feature():
    # feature 0 informative (= label), feature 1 = bruit
    X = [[float(i % 2), 0.5] for i in range(100)]
    y = [i % 2 for i in range(100)]

    def predict(rows):
        return [r[0] for r in rows]                       # utilise seulement la feature 0

    imp = permutation_importance(predict, X, y)
    assert imp[0] > imp[1]                                # feature 0 bien plus importante


def test_ks_detects_drift():
    a = [float(i) for i in range(100)]
    same = [float(i) for i in range(100)]
    shifted = [float(i) + 100 for i in range(100)]
    assert ks_statistic(a, same) < 0.05
    assert ks_statistic(a, shifted) > 0.9


def test_pca_finds_main_axis():
    # données variant surtout sur l'axe 0
    X = [[float(i), 0.01 * ((i % 3) - 1)] for i in range(60)]
    v = pca_first_component(X)
    assert abs(v[0]) > abs(v[1])                          # composante principale ≈ axe 0


def test_pca_sur_entree_vide_ne_plante_pas():
    """Fuzzing de l'audit : X vide levait IndexError et faisait tomber le bot."""
    from hl_observer.backtesting.ml_diagnostics import pca_first_component
    assert pca_first_component([]) == []
