"""S3 — orthogonalisation : repérer les signaux redondants (le même pari deux fois)."""
from __future__ import annotations

import pytest

from hl_observer.signals.orthogonalize import correlation, paires_redondantes


def test_correlation():
    a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert correlation(a, a) == pytest.approx(1.0)
    assert correlation(a, [-x for x in a]) == pytest.approx(-1.0)
    assert correlation([1.0], [1.0]) is None               # trop peu


def test_paires_redondantes():
    a = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    sig = {"x": a, "x_bis": [v * 2 for v in a], "bruit": [10, -3, 7, 1, -8, 4, 0, 6, -2, 9]}
    red = paires_redondantes(sig, seuil=0.9)
    assert ("x", "x_bis", pytest.approx(1.0, abs=1e-6)) in [(p[0], p[1], p[2]) for p in red]
