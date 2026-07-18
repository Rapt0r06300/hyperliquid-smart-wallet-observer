"""K1 — baseline linéaire (OLS) : la référence à battre avant toute ML."""
from __future__ import annotations

import pytest

from hl_observer.modeling.linear_baseline import ajuster_ols, predire, r2


def test_ols_recupere_la_droite():
    X = [[x] for x in range(12)]
    y = [2.0 * x + 3.0 for x in range(12)]      # y = 2x + 3
    coefs, intercept = ajuster_ols(X, y)
    assert coefs[0] == pytest.approx(2.0, abs=1e-6)
    assert intercept == pytest.approx(3.0, abs=1e-6)
    assert r2(coefs, intercept, X, y) == pytest.approx(1.0, abs=1e-9)


def test_predire():
    coefs, intercept = ajuster_ols([[x] for x in range(12)], [2.0 * x + 3.0 for x in range(12)])
    assert predire(coefs, intercept, [100.0]) == pytest.approx(203.0, abs=1e-4)


def test_deny_by_default_trop_peu():
    assert ajuster_ols([[1.0], [2.0]], [1.0, 2.0]) is None
