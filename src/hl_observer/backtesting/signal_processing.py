"""Traitement du signal & cointégration — pur, testé. Exécution du backlog :
haar_wavelet_transform (IDEA-86, décomposition multi-échelle), engle_granger_spread (IDEA-85,
cointégration pour pairs trading). Aucun ordre, aucune promesse.
"""
from __future__ import annotations

import math


def _finite_series(series, *, field: str) -> list[float]:
    values: list[float] = []
    for value in series:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{field} must contain only finite numeric values")
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError(f"{field} must contain only finite numeric values")
        values.append(parsed)
    return values


def haar_wavelet_transform(series) -> tuple:
    """Transformée de Haar (1 niveau) : (approximations lissées, détails). Un signal constant a des
    détails nuls ; les détails capturent les changements haute-fréquence."""
    xs = _finite_series(series, field="series")
    if len(xs) % 2:
        raise ValueError("series length must be even for a lossless Haar level")
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
    a_values = _finite_series(a, field="a")
    b_values = _finite_series(b, field="b")
    n = min(len(a_values), len(b_values))
    if n < 3:
        return {"beta": 0.0, "spread": [], "spread_autocorr": 1.0}
    ma = sum(a_values[:n]) / n
    mb = sum(b_values[:n]) / n
    cov = sum((b_values[i] - mb) * (a_values[i] - ma) for i in range(n))
    var_b = sum((b_values[i] - mb) ** 2 for i in range(n))
    beta = cov / var_b if var_b > 0 else 0.0
    alpha = ma - beta * mb
    spread = [a_values[i] - (alpha + beta * b_values[i]) for i in range(n)]
    ms = sum(spread) / len(spread)
    num = sum((spread[i] - ms) * (spread[i - 1] - ms) for i in range(1, len(spread)))
    den = sum((s - ms) ** 2 for s in spread)
    ac = num / den if den > 0 else 0.0
    return {"beta": beta, "spread": spread, "spread_autocorr": ac}
