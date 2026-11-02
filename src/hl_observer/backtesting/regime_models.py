"""Modèles de régime — pur, testé. Exécution du backlog :
gaussian_hmm_viterbi (IDEA-81, décodage HMM), fit_two_regimes (IDEA-90, regime-switching calme/
volatil). Aucun ordre, aucune promesse.
"""
from __future__ import annotations

import math


def _finite_values(values, *, field: str) -> list[float]:
    result: list[float] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} must contain only finite numeric values")
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"{field} must contain only finite numeric values")
        result.append(parsed)
    return result


def _gauss_logpdf(x, mu, sd):
    if sd <= 0 or not math.isfinite(sd):
        raise ValueError("standard deviations must be finite and positive")
    return -0.5 * math.log(2 * math.pi * sd * sd) - (x - mu) ** 2 / (2 * sd * sd)


def gaussian_hmm_viterbi(obs, means, stds, trans, init) -> list:
    """Décodage de Viterbi d'un HMM gaussien : renvoie la séquence d'états la plus probable."""
    observations = _finite_values(obs, field="observations")
    means_values = _finite_values(means, field="means")
    std_values = _finite_values(stds, field="stds")
    init_values = _finite_values(init, field="init")
    K, T = len(means_values), len(observations)
    if K == 0 or len(std_values) != K or len(init_values) != K:
        raise ValueError("HMM state vectors must have the same non-zero length")
    if len(trans) != K or any(len(row) != K for row in trans):
        raise ValueError("HMM transition matrix must be square")
    trans_values = [_finite_values(row, field="transition row") for row in trans]
    if any(value < 0.0 for row in trans_values for value in row):
        raise ValueError("HMM probabilities must be non-negative")
    if any(value < 0.0 for value in init_values):
        raise ValueError("HMM initial probabilities must be non-negative")
    if sum(init_values) <= 0.0 or any(sum(row) <= 0.0 for row in trans_values):
        raise ValueError("HMM probabilities must contain positive mass")
    if T == 0:
        return []
    lt = [[math.log(trans_values[i][j]) if trans_values[i][j] > 0 else -1e18 for j in range(K)] for i in range(K)]
    delta = [[-1e18] * K for _ in range(T)]
    psi = [[0] * K for _ in range(T)]
    for k in range(K):
        delta[0][k] = (math.log(init_values[k]) if init_values[k] > 0 else -1e18) + _gauss_logpdf(observations[0], means_values[k], std_values[k])
    for t in range(1, T):
        for k in range(K):
            best_j, best_val = 0, -1e18
            for j in range(K):
                v = delta[t - 1][j] + lt[j][k]
                if v > best_val:
                    best_val, best_j = v, j
            delta[t][k] = best_val + _gauss_logpdf(observations[t], means_values[k], std_values[k])
            psi[t][k] = best_j
    path = [0] * T
    path[T - 1] = max(range(K), key=lambda k: delta[T - 1][k])
    for t in range(T - 2, -1, -1):
        path[t] = psi[t + 1][path[t + 1]]
    return path


def fit_two_regimes(returns, *, iters: int = 10) -> tuple:
    """Hard-EM à 2 régimes sur |rendement| : 0 = calme, 1 = volatil. Retourne (labels, (moy0, moy1))."""
    if type(iters) is not int or iters < 1:
        raise ValueError("iters must be a positive integer")
    xs = [abs(value) for value in _finite_values(returns, field="returns")]
    if len(xs) < 4:
        return [0] * len(xs), (0.0, 0.0)
    m0, m1 = min(xs), max(xs)
    labels = [0] * len(xs)
    for _ in range(iters):
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
