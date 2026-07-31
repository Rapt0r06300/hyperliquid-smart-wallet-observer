"""ALPHA P43 — validation PURGED + EMBARGO pour horizons chevauchants (anti-fuite).

Quand la cible d'un point utilise un horizon futur, les points de train trop proches du test FUITENT. On
PURGE une zone autour du test et on ajoute un EMBARGO après. Fournit aussi un test de stabilité de préfixe.
Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from typing import Any


def splits_purged(n: int, *, n_folds: int = 5, horizon: int = 1, embargo: int = 0) -> list[dict[str, Any]]:
    """Retourne des folds {test: [i0,i1), train: indices} avec purge (horizon) + embargo autour du test."""
    if n < n_folds or n_folds < 2:
        return []
    taille = n // n_folds
    folds = []
    for k in range(n_folds):
        t0 = k * taille
        t1 = n if k == n_folds - 1 else (k + 1) * taille
        purge_lo = t0 - horizon
        purge_hi = t1 + horizon + embargo
        train = [i for i in range(n) if i < purge_lo or i >= purge_hi]
        folds.append({"test": (t0, t1), "train": train, "purge": (purge_lo, purge_hi)})
    return folds


def fuite_presente(train: list[int], test: tuple[int, int], *, horizon: int) -> bool:
    """True s'il reste un point de train à moins de `horizon` du test (fuite non purgée)."""
    t0, t1 = test
    for i in train:
        if t0 - horizon <= i < t1 + horizon:
            return True
    return False


def prefix_stable(decisions_complet: list[Any], decisions_prefixe: list[Any]) -> bool:
    """Stabilité de préfixe : tronquer le futur ne doit PAS changer les décisions passées."""
    k = len(decisions_prefixe)
    return decisions_complet[:k] == decisions_prefixe


__all__ = ["splits_purged", "fuite_presente", "prefix_stable"]
