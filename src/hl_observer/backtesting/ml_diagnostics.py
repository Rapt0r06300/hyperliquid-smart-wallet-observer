"""Diagnostics ML — pur, testé. Exécution du backlog :
permutation_importance (IDEA-09, importance des features type SHAP-lite), ks_statistic (IDEA-78,
détection de data drift), pca_first_component (IDEA-05, auto-encodeur linéaire / état latent).
Aucun ordre, aucune promesse.
"""
from __future__ import annotations

import bisect
import math
import random


def permutation_importance(predict_fn, X, y, *, seed: int = 0) -> list:
    """Baisse d'accuracy quand on mélange chaque feature = son importance."""
    def acc(preds):
        return sum(1 for i in range(len(y)) if (preds[i] > 0.5) == bool(y[i])) / len(y)

    base = acc(predict_fn(X))
    d = len(X[0])
    rng = random.Random(seed)
    imp = []
    for j in range(d):
        shuffled = [X[i][j] for i in range(len(X))]
        rng.shuffle(shuffled)
        Xp = [list(X[i]) for i in range(len(X))]
        for i in range(len(X)):
            Xp[i][j] = shuffled[i]
        imp.append(base - acc(predict_fn(Xp)))
    return imp


def ks_statistic(a, b) -> float:
    """Statistique de Kolmogorov-Smirnov entre 2 échantillons (0 = identiques, 1 = disjoints)."""
    sa, sb = sorted(a), sorted(b)
    if not sa or not sb:
        return 0.0
    def cdf(s, v):
        return bisect.bisect_right(s, v) / len(s)
    return max(abs(cdf(sa, v) - cdf(sb, v)) for v in sorted(set(sa) | set(sb)))


def pca_first_component(X, *, iters: int = 50) -> list:
    """1re composante principale via power iteration (bottleneck=1 d'un auto-encodeur linéaire).

    ROBUSTESSE (fuzzing de l'audit 2026-07-11) : X vide levait IndexError -> le bot tombait.
    Règle du projet : donnée manquante = état vide honnête, jamais un crash.
    """
    if not X or not X[0]:
        return []
    n, d = len(X), len(X[0])
    means = [sum(X[i][j] for i in range(n)) / n for j in range(d)]
    Xc = [[X[i][j] - means[j] for j in range(d)] for i in range(n)]
    v = [1.0] * d
    for _ in range(int(iters)):
        w = [0.0] * d
        for i in range(n):
            dot = sum(Xc[i][j] * v[j] for j in range(d))
            for j in range(d):
                w[j] += dot * Xc[i][j]
        norm = math.sqrt(sum(x * x for x in w)) or 1.0
        v = [x / norm for x in w]
    return v
