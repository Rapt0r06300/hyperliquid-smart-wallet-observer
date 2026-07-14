"""Signaux de marché — pur, testé. Exécution du backlog :
rolling_correlation (IMPROVE-33, corrélation inter-coins), anomaly_zscores (IMPROVE-35, spikes),
dominant_cycle (IDEA-89, analyse spectrale). No-lookahead (fenêtre passée). Aucun ordre.
"""
from __future__ import annotations

import math

from hl_observer.backtesting.portfolio_risk import correlation


def rolling_correlation(a, b, *, window: int = 30) -> float:
    """Corrélation sur la dernière fenêtre (contexte inter-coins : BTC bouge -> alt suit ?)."""
    n = min(len(a), len(b))
    w = min(window, n)
    if w < 2:
        return 0.0
    return correlation(list(a[-w:]), list(b[-w:]))


def anomaly_zscores(series, *, window: int = 30, threshold: float = 3.0) -> list:
    """Indices où la valeur est un SPIKE (|z| >= threshold), z calculé sur la fenêtre PRÉCÉDENTE
    uniquement (no-lookahead). Sert de signal de contexte/risque (volume/funding anormal)."""
    xs = [float(v) for v in series]
    out = []
    for i in range(window, len(xs)):
        w = xs[i - window:i]
        m = sum(w) / len(w)
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / len(w))
        if sd > 0 and abs((xs[i] - m) / sd) >= threshold:
            out.append(i)
    return out


def dominant_cycle(series):
    """Période dominante via DFT (pic de magnitude hors composante continue). None si trop court."""
    xs = [float(v) for v in series]
    n = len(xs)
    if n < 4:
        return None
    m = sum(xs) / n
    xs = [x - m for x in xs]
    best_k, best_mag = 0, -1.0
    for k in range(1, n // 2):
        re = sum(xs[t] * math.cos(2 * math.pi * k * t / n) for t in range(n))
        im = sum(xs[t] * math.sin(2 * math.pi * k * t / n) for t in range(n))
        mag = re * re + im * im
        if mag > best_mag:
            best_mag, best_k = mag, k
    return n / best_k if best_k > 0 else None
