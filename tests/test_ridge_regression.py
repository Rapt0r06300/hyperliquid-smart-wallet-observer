"""K2 — ridge : régularisation qui rétrécit les poids (moins d'overfit)."""
from __future__ import annotations

from hl_observer.modeling.ridge_regression import ajuster_ridge

X = [[float(x)] for x in range(20)]
Y = [2.0 * x + 3.0 for x in range(20)]


def test_alpha_faible_proche_ols():
    coefs, _ = ajuster_ridge(X, Y, alpha=1e-6)
    assert abs(coefs[0] - 2.0) < 0.01               # quasi OLS


def test_alpha_fort_retrecit_les_poids():
    coefs_faible, _ = ajuster_ridge(X, Y, alpha=1e-6)
    coefs_fort, _ = ajuster_ridge(X, Y, alpha=1000.0)
    assert abs(coefs_fort[0]) < abs(coefs_faible[0])  # le poids retrecit vers 0


def test_deny_by_default_trop_peu():
    assert ajuster_ridge([[1.0]], [1.0]) is None
