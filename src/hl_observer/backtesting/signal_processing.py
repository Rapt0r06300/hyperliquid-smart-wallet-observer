"""Traitement du signal & cointégration — pur, testé. Exécution du backlog :
haar_wavelet_transform (IDEA-86, décomposition multi-échelle), engle_granger_spread (IDEA-85,
cointégration pour pairs trading). Aucun ordre, aucune promesse.
"""
from __future__ import annotations

import math


def haar_wavelet_transform(series) -> tuple:
    """Transformée de Haar (1 niveau) : (approximations lissées, détails). Un signal constant a des
    détails nuls ; les détails capturent les changements haute-fréquence."""
    xs = [float(v) for v in series]
    n = len(xs) - (len(xs) % 2)
    root2 = math.sqrt(2.0)
    approx, detail = [], []
    for i in range(0, n, 2):
        approx.append((xs[i] + xs[i + 1]) / root2)
        detail.append((xs[i] - xs[i + 1]) / root2)
    return approx, detail


def engle_granger_spread(a, b) -> dict:
    """Régresse a sur b (moindres carrés) et analyse le spread résiduel. `spread_autocorr` proche de
    1 = spread type random-walk (NON cointégré) ; proche de 0 = mean-reverting (cointégré -> pairs)."""
    n = min(len(a), len(b))
    if n < 3:
        return {"beta": 0.0, "spread": [], "spread_autocorr": 1.0}
    ma = sum(a[:n]) / n
    mb = sum(b[:n]) / n
    cov = sum((b[i] - mb) * (a[i] - ma) for i in range(n))
    var_b = sum((b[i] - mb) ** 2 for i in range(n))
    beta = cov / var_b if var_b > 0 else 0.0
    alpha = ma - beta * mb
    spread = [a[i] - (alpha + beta * b[i]) for i in range(n)]
    ms = sum(spread) / len(spread)
    num = sum((spread[i] - ms) * (spread[i - 1] - ms) for i in range(1, len(spread)))
    den = sum((s - ms) ** 2 for s in spread)
    ac = num / den if den > 0 else 0.0
    return {"beta": beta, "spread": spread, "spread_autocorr": ac}
