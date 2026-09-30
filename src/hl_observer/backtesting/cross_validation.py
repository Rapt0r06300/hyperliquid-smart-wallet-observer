"""Validation croisée avancée — pur, testé. Exécution du backlog :
purged_walk_forward_splits (IDEA-30, purge+embargo), combinatorial_purged_splits (IDEA-21, CPCV),
whites_reality_check (IDEA-27). Anti-fuite temporelle + significativité. Aucun ordre.
"""
from __future__ import annotations

import random
from itertools import combinations


def purged_walk_forward_splits(n: int, *, n_splits: int = 5, embargo: int = 0) -> list:
    """Walk-forward : test = blocs successifs ; train = UNIQUEMENT le passé, purgé d'un embargo
    (on retire les 'embargo' observations juste avant le test pour éviter la contamination)."""
    if n_splits < 1 or n < n_splits:
        return []
    fold = n // n_splits
    splits = []
    for i in range(n_splits):
        start = i * fold
        end = n if i == n_splits - 1 else (i + 1) * fold
        test = list(range(start, end))
        train = list(range(0, max(0, start - embargo)))
        if test:
            splits.append((train, test))
    return splits


def combinatorial_purged_splits(n_groups: int, k_test: int) -> list:
    """CPCV : toutes les combinaisons de k_test groupes en test, le reste en train."""
    out = []
    for combo in combinations(range(n_groups), k_test):
        test = set(combo)
        train = [g for g in range(n_groups) if g not in test]
        out.append((train, list(combo)))
    return out


def whites_reality_check(strategy_best, benchmark, *, n: int = 1000, seed: int = 7) -> float:
    """p-value bootstrap : la surperformance de la MEILLEURE stratégie vs benchmark est-elle réelle
    ou du hasard ? Petit (<0.05) = significatif ; ~0.5 = indistinct du hasard."""
    m = min(len(strategy_best), len(benchmark))
    diff = [float(strategy_best[i]) - float(benchmark[i]) for i in range(m)]
    if not diff:
        return 1.0
    obs = sum(diff) / len(diff)
    centered = [d - obs for d in diff]          # sous H0 : moyenne nulle
    rng = random.Random(seed)
    L = len(centered)
    count = 0
    for _ in range(int(n)):
        s = sum(centered[rng.randrange(L)] for _ in range(L)) / L
        if s >= obs:
            count += 1
    return count / n
