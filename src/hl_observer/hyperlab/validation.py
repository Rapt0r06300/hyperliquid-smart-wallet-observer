"""[Bloc 47-49 / AUD-229,231,232,233,235,250,251-253,295] Validation statistique anti-overfit.

- cpcv_splits : Combinatorial Purged Cross-Validation (purge + embargo).
- pbo : Probability of Backtest Overfitting (rang IS-best vs OOS, Bailey/Lopez de Prado, simplifiee).
- deflated_sharpe : Deflated Sharpe Ratio (penalise le nombre d'essais).
- spa_pvalue : Superior Predictive Ability (bootstrap stationnaire simplifie).
- placebo_pvalue : test placebo par permutation du signal.
- leave_one_group_out : LOO par session/wallet/venue/coin/regime.
- ablation_marginale : valeur marginale OOS d'une source (garder/retirer).
numpy requis. deterministe (seed fixe la ou du hasard intervient)."""
from __future__ import annotations

import itertools
import math
from typing import Sequence

import numpy as np


def cpcv_splits(n_groups: int, k_test: int, embargo: int = 0) -> list:
    """Retourne [(train_idx, test_idx)] pour chaque combinaison de k_test groupes en test, avec purge
    des groupes adjacents (embargo)."""
    groupes = list(range(n_groups))
    out = []
    for combo in itertools.combinations(groupes, k_test):
        test = set(combo)
        purge = set()
        for t in combo:
            for e in range(1, embargo + 1):
                purge.add(t - e)
                purge.add(t + e)
        train = [g for g in groupes if g not in test and g not in purge]
        out.append((train, sorted(test)))
    return out


def pbo(perf_is: Sequence[float], perf_oos: Sequence[float]) -> dict:
    """PBO simplifiee : proba que la config choisie en IS (la meilleure) soit sous la MEDIANE OOS.
    perf_is/perf_oos alignes par config. Retourne pbo in [0,1] via rang."""
    is_a = np.asarray(perf_is, float)
    oos_a = np.asarray(perf_oos, float)
    best = int(np.argmax(is_a))
    med = float(np.median(oos_a))
    rang = float(np.mean(oos_a <= oos_a[best]))  # rang OOS de la config IS-best
    return {"config_is_best": best, "oos_best_config": float(oos_a[best]),
            "oos_median": med, "pbo": 1.0 - rang, "surclasse_mediane": bool(oos_a[best] >= med)}


def deflated_sharpe(sr_obs: float, n_trials: int, T: int, skew: float = 0.0, kurt: float = 3.0) -> dict:
    """DSR : Sharpe deflate par le max attendu sous H0 sur n_trials. Retourne dsr (prob) in [0,1]."""
    if n_trials < 1 or T < 2:
        return {"dsr": None, "raison": "parametres_insuffisants"}
    emc = 0.5772156649
    e_max = math.sqrt(2 * math.log(max(n_trials, 2))) * (1 - emc / (2 * math.log(max(n_trials, 2))))
    sr0 = e_max / math.sqrt(T)  # seuil attendu du max sous H0 (approx, SR non annualise)
    denom = math.sqrt((1 - skew * sr_obs + (kurt - 1) / 4.0 * sr_obs ** 2) / (T - 1))
    if denom == 0:
        return {"dsr": None, "raison": "denominateur_nul"}
    z = (sr_obs - sr0) / denom
    dsr = 0.5 * (1 + math.erf(z / math.sqrt(2)))
    return {"dsr": dsr, "sr0_attendu": sr0, "z": z}


def spa_pvalue(perf_relative: Sequence[float], n_boot: int = 1000, seed: int = 0) -> dict:
    """SPA (Hansen) simplifie : H0 = pas de perf superieure. perf_relative = surperformance par periode
    (model - benchmark). p-value par bootstrap stationnaire (blocs). petit p => edge reel."""
    x = np.asarray(perf_relative, float)
    n = len(x)
    if n < 4:
        return {"p_value": None, "raison": "serie_trop_courte"}
    rng = np.random.default_rng(seed)
    mean = x.mean()
    t_obs = mean / (x.std(ddof=1) / math.sqrt(n) + 1e-12)
    xc = x - mean  # sous H0, moyenne nulle
    boot = np.empty(n_boot)
    L = max(2, int(round(n ** (1 / 3))))
    for b in range(n_boot):
        idx = []
        while len(idx) < n:
            start = int(rng.integers(0, n))
            idx.extend([(start + j) % n for j in range(L)])
        s = xc[np.asarray(idx[:n])]
        boot[b] = s.mean() / (s.std(ddof=1) / math.sqrt(n) + 1e-12)
    p = float(np.mean(boot >= t_obs))
    return {"p_value": p, "t_obs": float(t_obs)}


def placebo_pvalue(signal: Sequence[float], returns: Sequence[float], n_perm: int = 1000, seed: int = 0) -> dict:
    """Test placebo : correlation signal->rendement vs permutations aleatoires du signal. petit p => reel."""
    s = np.asarray(signal, float)
    r = np.asarray(returns, float)
    if len(s) != len(r) or len(s) < 4:
        return {"p_value": None, "raison": "series_incompatibles"}
    rng = np.random.default_rng(seed)
    obs = float(np.corrcoef(s, r)[0, 1])
    cnt = 0
    for _ in range(n_perm):
        if abs(float(np.corrcoef(rng.permutation(s), r)[0, 1])) >= abs(obs):
            cnt += 1
    return {"p_value": (cnt + 1) / (n_perm + 1), "corr_obs": obs}


def leave_one_group_out(groupes: Sequence) -> list:
    uniq = sorted(set(groupes))
    return [(g, [x for x in uniq if x != g]) for g in uniq]


def ablation_marginale(perf_avec: float, perf_sans: float, *, seuil: float = 0.0) -> dict:
    """Valeur marginale OOS d'une source = perf_avec - perf_sans. Sous le seuil -> retirer (AUD-295/364)."""
    marge = float(perf_avec) - float(perf_sans)
    return {"marge_oos": marge, "garder": marge > seuil}
