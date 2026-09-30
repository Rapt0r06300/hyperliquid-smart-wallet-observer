"""Modèles de régime — pur, testé. Exécution du backlog :
gaussian_hmm_viterbi (IDEA-81, décodage HMM), fit_two_regimes (IDEA-90, regime-switching calme/
volatil). Aucun ordre, aucune promesse.
"""
from __future__ import annotations

import math


def _gauss_logpdf(x, mu, sd):
    sd = sd if sd > 0 else 1e-9
    return -0.5 * math.log(2 * math.pi * sd * sd) - (x - mu) ** 2 / (2 * sd * sd)


def gaussian_hmm_viterbi(obs, means, stds, trans, init) -> list:
    """Décodage de Viterbi d'un HMM gaussien : renvoie la séquence d'états la plus probable."""
    K, T = len(means), len(obs)
    if T == 0:
        return []
    lt = [[math.log(trans[i][j]) if trans[i][j] > 0 else -1e18 for j in range(K)] for i in range(K)]
    delta = [[-1e18] * K for _ in range(T)]
    psi = [[0] * K for _ in range(T)]
    for k in range(K):
        delta[0][k] = (math.log(init[k]) if init[k] > 0 else -1e18) + _gauss_logpdf(obs[0], means[k], stds[k])
    for t in range(1, T):
        for k in range(K):
            best_j, best_val = 0, -1e18
            for j in range(K):
                v = delta[t - 1][j] + lt[j][k]
                if v > best_val:
                    best_val, best_j = v, j
            delta[t][k] = best_val + _gauss_logpdf(obs[t], means[k], stds[k])
            psi[t][k] = best_j
    path = [0] * T
    path[T - 1] = max(range(K), key=lambda k: delta[T - 1][k])
    for t in range(T - 2, -1, -1):
        path[t] = psi[t + 1][path[t + 1]]
    return path


def fit_two_regimes(returns, *, iters: int = 10) -> tuple:
    """Hard-EM à 2 régimes sur |rendement| : 0 = calme, 1 = volatil. Retourne (labels, (moy0, moy1))."""
    xs = [abs(float(r)) for r in returns]
    if len(xs) < 4:
        return [0] * len(xs), (0.0, 0.0)
    m0, m1 = min(xs), max(xs)
    labels = [0] * len(xs)
    for _ in range(int(iters)):
        labels = [0 if abs(x - m0) <= abs(x - m1) else 1 for x in xs]
        c0 = [xs[i] for i in range(len(xs)) if labels[i] == 0]
        c1 = [xs[i] for i in range(len(xs)) if labels[i] == 1]
        if c0:
            m0 = sum(c0) / len(c0)
        if c1:
            m1 = sum(c1) / len(c1)
    if m0 > m1:
        m0, m1 = m1, m0
        labels = [1 - v for v in labels]
    return labels, (m0, m1)
