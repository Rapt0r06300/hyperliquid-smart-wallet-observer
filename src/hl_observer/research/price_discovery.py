"""ALPHA P19 — DYNAMIC PRICE DISCOVERY : qui mène le prix ? cross-corrélation + lead-lag asynchrone → venue_leader_score.

Pour deux venues, on mesure la corrélation croisée des rendements à différents lags : un pic à lag>0 signifie
que la venue A précède la venue B. On agrège en un `venue_leader_score` par venue (à quel point elle mène).
Information Share / Hayashi-Yoshida sont branchables plus tard ; ici la version cross-corr, robuste et testable.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    n = len(xs)
    if n < 5:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy)


def crosscorr_lead(ret_a: Sequence[float], ret_b: Sequence[float], *, max_lag: int = 5) -> dict[str, Any]:
    """corr(ret_a[t], ret_b[t+k]). Pic à k>0 ⇒ A précède B (A mène)."""
    n = min(len(ret_a), len(ret_b))
    corr: dict[int, float | None] = {}
    for k in range(-max_lag, max_lag + 1):
        xs, ys = [], []
        for t in range(n):
            if 0 <= t + k < n:
                xs.append(ret_a[t]); ys.append(ret_b[t + k])
        corr[k] = _pearson(xs, ys)
    valides = {k: v for k, v in corr.items() if v is not None}
    peak = max(valides, key=lambda k: valides[k]) if valides else None
    return {"corr_par_lag": corr, "peak_lag": peak, "a_mene": (peak is not None and peak > 0)}


def venue_leader_score(rendements_par_venue: Mapping[str, Sequence[float]], *, max_lag: int = 5) -> dict[str, float]:
    """Pour chaque paire de venues, qui mène ; score par venue = fraction des paires où elle mène."""
    venues = list(rendements_par_venue)
    gagne: dict[str, int] = {v: 0 for v in venues}
    total: dict[str, int] = {v: 0 for v in venues}
    for i in range(len(venues)):
        for j in range(i + 1, len(venues)):
            a, b = venues[i], venues[j]
            r = crosscorr_lead(rendements_par_venue[a], rendements_par_venue[b], max_lag=max_lag)
            if r["peak_lag"] is None:
                continue
            total[a] += 1; total[b] += 1
            if r["peak_lag"] > 0:
                gagne[a] += 1
            elif r["peak_lag"] < 0:
                gagne[b] += 1
    return {v: round(gagne[v] / total[v], 4) if total[v] else 0.0 for v in venues}


__all__ = ["crosscorr_lead", "venue_leader_score"]
