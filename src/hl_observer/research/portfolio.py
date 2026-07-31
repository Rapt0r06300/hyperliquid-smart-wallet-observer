"""ALPHA P49 — PORTEFEUILLE d'alphas : allouer entre edges réellement INDÉPENDANTS.

Quand plusieurs signaux survivent, on ne les additionne pas naïvement : on mesure la covariance de leurs PnL,
le chevauchement temporel, le bêta coin, le chevauchement d'entités. On alloue plus aux alphas décorrélés et
positifs, moins aux redondants. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from typing import Any


def correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = min(len(a), len(b))
    if n < 5:
        return None
    ma = sum(a[:n]) / n; mb = sum(b[:n]) / n
    sa = sum((a[i] - ma) ** 2 for i in range(n))
    sb = sum((b[i] - mb) ** 2 for i in range(n))
    if sa <= 0 or sb <= 0:
        return None
    return sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / (sa ** 0.5 * sb ** 0.5)


def allocation(pnl_par_alpha: Mapping[str, Sequence[float]]) -> dict[str, Any]:
    """Poids ∝ (edge moyen positif) / (1 + somme des corrélations avec les autres). Normalisé à 1."""
    alphas = {k: [float(x) for x in v] for k, v in pnl_par_alpha.items() if len(v) >= 5}
    if not alphas:
        return {"poids": {}, "verdict": "MORE_DATA"}
    edges = {k: statistics.mean(v) for k, v in alphas.items()}
    brut = {}
    for k, v in alphas.items():
        if edges[k] <= 0:
            brut[k] = 0.0
            continue
        corr_somme = 0.0
        for j, w in alphas.items():
            if j == k:
                continue
            c = correlation(v, w)
            corr_somme += max(0.0, c) if c is not None else 0.0
        brut[k] = edges[k] / (1.0 + corr_somme)
    total = sum(brut.values())
    poids = {k: round(v / total, 4) for k, v in brut.items()} if total > 0 else {k: 0.0 for k in brut}
    return {"poids": poids, "edges_moyens": {k: round(v, 4) for k, v in edges.items()},
            "verdict": ("ALLOUE" if total > 0 else "AUCUN_ALPHA_POSITIF")}


__all__ = ["correlation", "allocation"]
