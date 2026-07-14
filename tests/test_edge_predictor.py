"""Tests du predicteur from-scratch : il doit APPRENDRE un motif separable, et rester deterministe."""
from __future__ import annotations

from hl_observer.backtesting.edge_predictor import (
    apply_standardizer,
    features_of,
    fit_logreg,
    fit_standardizer,
    predict_proba,
)


def test_features_of_handles_missing():
    f = features_of({"edge_remaining_bps": 30.0})
    assert len(f) == 7 and f[0] == 30.0


def test_learns_separable_pattern():
    # classe 1 = feature elevee, classe 0 = feature basse -> le modele doit les separer
    X = [[float(v), 0.0] for v in range(-50, 0)] + [[float(v), 0.0] for v in range(1, 51)]
    y = [0] * 50 + [1] * 50
    m, s = fit_standardizer(X)
    Xs = apply_standardizer(X, m, s)
    w, b = fit_logreg(Xs, y, epochs=200)
    p = predict_proba(Xs, w, b)
    acc = sum(1 for i in range(len(y)) if (p[i] > 0.5) == bool(y[i])) / len(y)
    assert acc > 0.9


def test_deterministic():
    X = [[1.0, 2.0], [3.0, 1.0], [2.0, 2.0], [0.0, 1.0]]
    y = [1, 0, 1, 0]
    m, s = fit_standardizer(X); Xs = apply_standardizer(X, m, s)
    assert fit_logreg(Xs, y, epochs=50) == fit_logreg(Xs, y, epochs=50)


def test_entree_vide_ne_fait_pas_planter_le_modele():
    """BUG REEL trouve par le fuzzing : une entree vide levait IndexError et faisait tomber la
    boucle. Regle du projet : donnee manquante -> etat vide HONNETE, jamais un crash."""
    from hl_observer.backtesting.edge_predictor import features_of, fit_logreg, fit_standardizer
    assert fit_standardizer([]) == {"mean": [], "std": []}
    assert fit_logreg([], []) == {"w": [], "b": 0.0}
    assert all(v == 0.0 for v in features_of("pas un dict"))
