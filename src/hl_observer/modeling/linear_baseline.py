"""K1 — BASELINE LINÉAIRE AVANT TOUTE ML (rasoir d'Occam).

En trading, la ML sur-ajuste presque toujours le bruit. La discipline : d'abord une régression
LINÉAIRE simple comme référence. Si un modèle ML ne la bat pas NETTEMENT hors échantillon, on garde
le linéaire (moins d'overfit, explicable, robuste). Ce module fournit la baseline + son R² OOS.

PUR (numpy). Deny-by-default : trop peu de points -> None. PAPER only.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

MIN_POINTS = 10


def ajuster_ols(X: Sequence[Sequence[float]], y: Sequence[float]):
    """OLS : renvoie (coefs, intercept) ou None si insuffisant. X = liste de lignes (features)."""
    Xa = np.asarray(X, dtype=float)
    ya = np.asarray(y, dtype=float)
    if Xa.ndim == 1:
        Xa = Xa.reshape(-1, 1)
    if Xa.shape[0] < MIN_POINTS or Xa.shape[0] != ya.shape[0]:
        return None
    design = np.column_stack([np.ones(Xa.shape[0]), Xa])
    beta, *_ = np.linalg.lstsq(design, ya, rcond=None)
    return beta[1:], float(beta[0])


def predire(coefs, intercept: float, x: Sequence[float]) -> float:
    return float(intercept) + float(np.dot(np.asarray(coefs, float), np.asarray(x, float)))


def r2(coefs, intercept: float, X: Sequence[Sequence[float]], y: Sequence[float]) -> float | None:
    """R² sur (X, y) — à calculer sur un jeu HORS ÉCHANTILLON pour juger honnêtement."""
    Xa = np.asarray(X, float)
    ya = np.asarray(y, float)
    if Xa.ndim == 1:
        Xa = Xa.reshape(-1, 1)
    if Xa.shape[0] == 0:
        return None
    pred = intercept + Xa @ np.asarray(coefs, float)
    ss_res = float(np.sum((ya - pred) ** 2))
    ss_tot = float(np.sum((ya - ya.mean()) ** 2))
    return 1.0 - ss_res / ss_tot if ss_tot > 1e-12 else 0.0


__all__ = ["MIN_POINTS", "ajuster_ols", "predire", "r2"]
