"""Méthodes de validation avancées — pures, testées. Exécution du backlog :
stationary_bootstrap (IDEA-29), probability_of_backtest_overfitting/CSCV (IDEA-23),
min_track_record_length (IDEA-28, "longueur de backtest minimale"). Aucun ordre, aucune promesse.
"""
from __future__ import annotations

import math
import random
from itertools import combinations

from hl_observer.backtesting.quant_methods import _norm_ppf


def stationary_bootstrap(x, *, mean_block: int = 10, n: int = 1000, seed: int = 7) -> list:
    """Bootstrap stationnaire (Politis-Romano) : blocs de longueur géométrique -> préserve la
    dépendance temporelle sans couper aux mêmes endroits. Retourne n totaux rééchantillonnés."""
    xs = [float(v) for v in x]
    L = len(xs)
    if L == 0:
        return []
    p = 1.0 / max(1, mean_block)
    rng = random.Random(seed)
    out = []
    for _ in range(int(n)):
        s = 0.0
        count = 0
        idx = rng.randrange(L)
        while count < L:
            s += xs[idx]
            count += 1
            if rng.random() < p:
                idx = rng.randrange(L)          # nouveau bloc
            else:
                idx = (idx + 1) % L             # on continue le bloc
        out.append(s)
    return out


def min_track_record_length(sr: float, *, sr_star: float = 0.0, prob: float = 0.95,
                            skew: float = 0.0, kurt: float = 3.0) -> float:
    """Nombre minimal d'observations pour être 'prob' sûr que le vrai Sharpe > sr_star (López de Prado).
    Sharpe plus élevé -> moins d'observations requises ; SR <= sr_star -> impossible (inf)."""
    denom = sr - sr_star
    if denom <= 0:
        return float("inf")
    z = _norm_ppf(prob)
    return 1.0 + (1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr) * (z / denom) ** 2


def probability_of_backtest_overfitting(perf_matrix) -> float:
    """CSCV (Combinatorial Symmetric Cross-Validation). `perf_matrix` : S sous-périodes × N configs.
    Retourne PBO ∈ [0,1] : probabilité que la config la MEILLEURE en in-sample soit sous la médiane
    out-of-sample (= sur-apprentissage). Proche de 1 = très sur-appris ; proche de 0 = robuste."""
    S = len(perf_matrix)
    S -= S % 2
    if S < 2:
        return 0.5
    perf_matrix = perf_matrix[:S]
    N = len(perf_matrix[0])
    half = S // 2
    logits = []
    for combo in combinations(range(S), half):
        oos = [s for s in range(S) if s not in combo]
        is_perf = [sum(perf_matrix[s][c] for s in combo) for c in range(N)]
        oos_perf = [sum(perf_matrix[s][c] for s in oos) for c in range(N)]
        best = max(range(N), key=lambda c: is_perf[c])
        rank = sorted(range(N), key=lambda c: oos_perf[c]).index(best)  # 0=pire .. N-1=meilleur
        w = min(1 - 1e-9, max(1e-9, (rank + 1) / (N + 1)))
        logits.append(math.log(w / (1 - w)))
    return sum(1 for lg in logits if lg <= 0) / len(logits)
