"""Tests du ML avancé from-scratch."""
from __future__ import annotations

from hl_observer.backtesting.ml_extras import (
    bayesian_winrate,
    ensemble_average,
    gradient_boosting_fit,
    gradient_boosting_predict,
    online_sgd_update,
    platt_scaling,
)


def test_gradient_boosting_learns_pattern():
    X = [[float(v)] for v in range(-30, 31)]
    y = [1 if v > 0 else 0 for v in range(-30, 31)]
    stumps = gradient_boosting_fit(X, y, n_estimators=20)
    p = gradient_boosting_predict(X, stumps)
    acc = sum(1 for i in range(len(y)) if (p[i] > 0.5) == bool(y[i])) / len(y)
    assert acc > 0.9


def test_ensemble_average():
    assert ensemble_average([[0.2, 0.8], [0.4, 0.6]]) == [0.30000000000000004, 0.7]


def test_platt_scaling_calibrates():
    scores = [-5.0, -3.0, -1.0, 1.0, 3.0, 5.0] * 10
    labels = [0, 0, 0, 1, 1, 1] * 10
    a, b = platt_scaling(scores, labels)
    assert a > 0                                    # score plus haut -> proba plus haute


def test_online_sgd_moves_toward_target():
    w, b = [0.0], 0.0
    for _ in range(200):
        w, b = online_sgd_update(w, b, [2.0], 1)    # x positif, cible 1
    from hl_observer.backtesting.ml_extras import _sigmoid
    assert _sigmoid(w[0] * 2.0 + b) > 0.7


def test_bayesian_winrate_uncertainty_shrinks():
    few = bayesian_winrate(3, 2)
    many = bayesian_winrate(300, 200)
    assert abs(many["mean"] - 0.6) < 0.02
    assert many["sd"] < few["sd"]                   # plus de données -> moins d'incertitude


def test_entrees_vides_ne_plantent_pas():
    """Fuzzing de l'audit : IndexError et ZeroDivisionError sur listes vides."""
    from hl_observer.backtesting.ml_extras import gradient_boosting_fit, platt_scaling
    assert gradient_boosting_fit([], []) == []
    assert platt_scaling([], []) == (1.0, 0.0)      # calibration neutre, pas un crash
