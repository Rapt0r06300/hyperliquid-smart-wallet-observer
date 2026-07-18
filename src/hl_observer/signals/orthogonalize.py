"""S3 — ORTHOGONALISATION des signaux ENTRE EUX (pas seulement vs BTC, cf. H2).

Cinq features corrélées = le MÊME pari déguisé cinq fois -> on surpondère un seul risque. On mesure
la corrélation entre signaux et on signale les REDONDANTS (à fusionner/retirer avant de combiner).
PUR. Deny-by-default : trop peu de points -> non mesurable. PAPER only.
"""
from __future__ import annotations

from typing import Mapping, Sequence

MIN_POINTS = 10


def correlation(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = min(len(a or []), len(b or []))
    if n < MIN_POINTS:
        return None
    xa, xb = [float(x) for x in a[:n]], [float(x) for x in b[:n]]
    ma, mb = sum(xa) / n, sum(xb) / n
    cov = sum((xa[i] - ma) * (xb[i] - mb) for i in range(n))
    va = sum((x - ma) ** 2 for x in xa) ** 0.5
    vb = sum((x - mb) ** 2 for x in xb) ** 0.5
    return None if va <= 1e-12 or vb <= 1e-12 else cov / (va * vb)


def paires_redondantes(signaux: Mapping[str, Sequence[float]], *, seuil: float = 0.8) -> list[tuple[str, str, float]]:
    """Paires de signaux dont |corrélation| >= seuil (redondants : le même pari deux fois)."""
    noms = list((signaux or {}).keys())
    out = []
    for i in range(len(noms)):
        for j in range(i + 1, len(noms)):
            c = correlation(signaux[noms[i]], signaux[noms[j]])
            if c is not None and abs(c) >= float(seuil):
                out.append((noms[i], noms[j], round(c, 4)))
    return out


__all__ = ["MIN_POINTS", "correlation", "paires_redondantes"]
