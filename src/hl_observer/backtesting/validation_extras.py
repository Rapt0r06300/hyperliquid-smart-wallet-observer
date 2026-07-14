"""Validation supplémentaire — pur, testé. Exécution du backlog :
walk_forward_multi_window (IMPROVE-09, fenêtres glissantes), regime_split_indices (IMPROVE-10,
évaluation séparée par régime). Aucun ordre, aucune promesse.
"""
from __future__ import annotations

from hl_observer.backtesting.regime_models import fit_two_regimes


def walk_forward_multi_window(n: int, *, train_size: int, test_size: int, step: int | None = None) -> list:
    """Fenêtres glissantes successives (train fixe puis test), pas de fuite : train toujours avant test."""
    step = step or test_size
    splits = []
    start = 0
    while start + train_size + test_size <= n:
        train = list(range(start, start + train_size))
        test = list(range(start + train_size, start + train_size + test_size))
        splits.append((train, test))
        start += step
    return splits


def regime_split_indices(returns) -> dict:
    """Sépare les indices en régime CALME vs VOLATIL (via fit_two_regimes) pour évaluer une stratégie
    séparément par régime (elle peut gagner en calme et exploser en volatil)."""
    labels, _ = fit_two_regimes(returns)
    return {
        "calm": [i for i, v in enumerate(labels) if v == 0],
        "volatile": [i for i, v in enumerate(labels) if v == 1],
    }
