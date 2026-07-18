"""K2 — RÉGRESSION RÉGULARISÉE (Ridge L2) : des poids stables, moins d'overfit.

La régularisation empêche des poids énormes qui collent au bruit d'échantillon. Ridge : ferme,
`(X'X + alpha·I)^-1 X'y` (on NE pénalise PAS l'intercept). Plus alpha est grand, plus les poids
rétrécissent vers 0 -> moins de variance, plus de biais. PUR (numpy). PAPER only.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

MIN_POINTS = 10


def ajuster_ridge(X: Sequence[Sequence[float]], y: Sequence[float], *, alpha: float = 1.0):
    """Renvoie (coefs, intercept) avec pénalité L2 alpha (intercept non pénalisé). None si insuffisant."""
    Xa = np.asarray(X, dtype=float)
    ya = np.asarray(y, dtype=float)
    if Xa.ndim == 1:
        Xa = Xa.reshape(-1, 1)
    if Xa.shape[0] < MIN_POINTS or Xa.shape[0] != ya.shape[0]:
        return None
    n, d = Xa.shape
    design = np.column_stack([np.ones(n), Xa])
    penalite = float(alpha) * np.eye(d + 1)
    penalite[0, 0] = 0.0                                   # ne PAS pénaliser l'intercept
    beta = np.linalg.solve(design.T @ design + penalite, design.T @ ya)
    return beta[1:], float(beta[0])


__all__ = ["MIN_POINTS", "ajuster_ridge"]
