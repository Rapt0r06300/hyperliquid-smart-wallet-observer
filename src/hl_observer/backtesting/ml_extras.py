"""ML avancé FROM SCRATCH (zéro dépendance) — pur, testé. Exécution du backlog :
gradient_boosting_fit/predict (IDEA-01), ensemble_average (IDEA-07), platt_scaling (IDEA-08),
online_sgd_update (IDEA-10), bayesian_winrate (IDEA-06). Aucun ordre, aucune promesse.
"""
from __future__ import annotations

import math


def _sigmoid(z):
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def _best_stump(X, residuals):
    n, d = len(X), len(X[0])
    best = (0, 0.0, 0.0, 0.0, float("inf"))
    for j in range(d):
        for thr in sorted(set(x[j] for x in X)):
            left = [residuals[i] for i in range(n) if X[i][j] <= thr]
            right = [residuals[i] for i in range(n) if X[i][j] > thr]
            if not left or not right:
                continue
            lv, rv = sum(left) / len(left), sum(right) / len(right)
            sse = sum((residuals[i] - (lv if X[i][j] <= thr else rv)) ** 2 for i in range(n))
            if sse < best[4]:
                best = (j, thr, lv, rv, sse)
    return best


def gradient_boosting_fit(X, y, *, n_estimators: int = 15, lr: float = 0.3) -> list:
    """Gradient boosting de souches de décision sur le gradient de la log-loss (classification).

    ROBUSTESSE (fuzzing 2026-07-11) : X vide levait IndexError -> modèle vide honnête.
    """
    if not X or not X[0]:
        return []
    pred = [0.0] * len(X)
    stumps = []
    for _ in range(int(n_estimators)):
        resid = [y[i] - _sigmoid(pred[i]) for i in range(len(X))]   # gradient fonctionnel
        j, thr, lv, rv, _ = _best_stump(X, resid)
        stumps.append((j, thr, lv, rv))
        for i in range(len(X)):
            pred[i] += lr * (lv if X[i][j] <= thr else rv)
    return stumps


def gradient_boosting_predict(X, stumps, *, lr: float = 0.3) -> list:
    out = []
    for x in X:
        s = 0.0
        for (j, thr, lv, rv) in stumps:
            s += lr * (lv if x[j] <= thr else rv)
        out.append(_sigmoid(s))
    return out


def ensemble_average(prob_lists) -> list:
    """Moyenne des probabilités de plusieurs modèles (ensembling)."""
    if not prob_lists:
        return []
    m = len(prob_lists)
    n = min(len(p) for p in prob_lists)
    return [sum(prob_lists[k][i] for k in range(m)) / m for i in range(n)]


def platt_scaling(scores, labels, *, epochs: int = 200, lr: float = 0.1):
    """Calibration de Platt : ajuste p = sigmoid(a*score + b) pour caler les probabilités.

    ROBUSTESSE (fuzzing 2026-07-11) : une liste vide provoquait une DIVISION PAR ZERO.
    """
    a, b = 1.0, 0.0
    n = len(scores)
    if n == 0:
        return (a, b)
    for _ in range(int(epochs)):
        ga = gb = 0.0
        for i in range(n):
            p = _sigmoid(a * scores[i] + b)
            err = p - labels[i]
            ga += err * scores[i]
            gb += err
        a -= lr * ga / n
        b -= lr * gb / n
    return a, b


def online_sgd_update(w, b, x, y, *, lr: float = 0.1):
    """Une mise à jour SGD (apprentissage en ligne, le modèle s'adapte au fil de l'eau)."""
    p = _sigmoid(sum(w[j] * x[j] for j in range(len(w))) + b)
    err = p - y
    w = [w[j] - lr * err * x[j] for j in range(len(w))]
    b = b - lr * err
    return w, b


def bayesian_winrate(wins: int, losses: int, *, prior_a: float = 1.0, prior_b: float = 1.0) -> dict:
    """Postérieur Beta du winrate + incertitude. mean = a/(a+b) ; sd décroît avec les données."""
    a = prior_a + wins
    b = prior_b + losses
    mean = a / (a + b)
    var = a * b / ((a + b) ** 2 * (a + b + 1))
    return {"mean": mean, "sd": math.sqrt(var), "a": a, "b": b}
