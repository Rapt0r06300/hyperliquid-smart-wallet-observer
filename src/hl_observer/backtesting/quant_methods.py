"""Boîte à outils quantitative avancée — pure, déterministe, testée. Exécution du backlog :
block_bootstrap (IMPROVE-49), fractional_diff (IDEA-26), deflated_sharpe (IDEA-22),
hurst_exponent (IDEA-88), shannon_entropy (IDEA-87). Outils de mesure/rigueur ; aucune promesse de
PnL, aucun ordre. Zéro dépendance externe.
"""
from __future__ import annotations

import math
import random
from statistics import fmean, pstdev


# ---------- Bootstrap par blocs (préserve l'autocorrélation) ----------
def block_bootstrap(x, *, block: int = 10, n: int = 1000, seed: int = 7) -> list:
    """Rééchantillonne la SÉQUENCE par blocs (avec remise) -> distribution du total (net PnL)."""
    xs = [float(v) for v in x]
    L = len(xs)
    if L == 0:
        return []
    block = max(1, min(block, L))
    rng = random.Random(seed)
    out = []
    for _ in range(int(n)):
        s = 0.0
        count = 0
        while count < L:
            start = rng.randrange(L)
            for k in range(block):
                s += xs[(start + k) % L]
                count += 1
                if count >= L:
                    break
        out.append(s)
    return out


# ---------- Différenciation fractionnaire (stationnarité sans perdre la mémoire) ----------
def fractional_diff(series, d: float, *, thresh: float = 1e-4) -> list:
    xs = [float(v) for v in series]
    w = [1.0]
    k = 1
    while k < len(xs):
        wk = -w[-1] * (d - k + 1) / k
        if abs(wk) < thresh:
            break
        w.append(wk)
        k += 1
    width = len(w) - 1
    out = []
    for i in range(width, len(xs)):
        out.append(sum(w[j] * xs[i - j] for j in range(len(w))))
    return out


# ---------- Sharpe déflaté (corrige la sur-recherche / comparaisons multiples) ----------
def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    if p <= 0.0:
        return -1e9
    if p >= 1.0:
        return 1e9
    a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2,
         1.383577518672690e2, -3.066479806614716e1, 2.506628277459239e0]
    b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2,
         6.680131188771972e1, -1.328068155288572e1]
    c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838e0,
         -2.549732539343734e0, 4.374664141464968e0, 2.938163982698783e0]
    d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996e0, 3.754408661907416e0]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def probabilistic_sharpe_ratio(sr: float, T: int, *, sr_star: float = 0.0,
                               skew: float = 0.0, kurt: float = 3.0) -> float:
    """Proba que le vrai Sharpe dépasse sr_star, vu T observations."""
    denom = math.sqrt(max(1e-9, 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr))
    z = (sr - sr_star) * math.sqrt(max(1, T - 1)) / denom
    return _norm_cdf(z)


def deflated_sharpe(
    sr: float,
    T: int,
    n_trials: int,
    *,
    sr_variance: float | None = None,
    trial_sharpes: list[float] | tuple[float, ...] | None = None,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> float:
    """Déflate le Sharpe pour le NOMBRE d'essais tentés (plus on cherche, plus le seuil monte)."""
    empirical = [float(value) for value in (trial_sharpes or ()) if math.isfinite(float(value))]
    if empirical:
        n_trials = max(int(n_trials), len(empirical))
        if len(empirical) > 1:
            mean = fmean(empirical)
            sr_variance = sum((value - mean) ** 2 for value in empirical) / (len(empirical) - 1)
    if sr_variance is None or sr_variance <= 0:
        sr_variance = 1.0 / max(1, T)
    if n_trials < 2:
        sr_star = 0.0
    else:
        e = 0.5772156649015329  # Euler-Mascheroni
        z1 = _norm_ppf(1.0 - 1.0 / n_trials)
        z2 = _norm_ppf(1.0 - 1.0 / (n_trials * math.e))
        sr_star = math.sqrt(sr_variance) * ((1.0 - e) * z1 + e * z2)
    return probabilistic_sharpe_ratio(sr, T, sr_star=sr_star, skew=skew, kurt=kurt)


# ---------- Exposant de Hurst (mean-reverting < 0.5 < trending) ----------
def hurst_exponent(series, *, max_lag: int = 20) -> float:
    xs = [float(v) for v in series]
    if len(xs) < max_lag + 2:
        return 0.5
    ll, tt = [], []
    for lag in range(2, max_lag):
        diffs = [xs[i + lag] - xs[i] for i in range(len(xs) - lag)]
        sd = pstdev(diffs) if len(diffs) > 1 else 0.0
        if sd > 0:
            ll.append(math.log(lag))
            tt.append(math.log(sd))
    if len(ll) < 2:
        return 0.5
    mx, my = fmean(ll), fmean(tt)
    num = sum((ll[i] - mx) * (tt[i] - my) for i in range(len(ll)))
    den = sum((ll[i] - mx) ** 2 for i in range(len(ll)))
    return num / den if den > 0 else 0.5


# ---------- Entropie de Shannon (mesure de prédictibilité) ----------
def shannon_entropy(values, *, bins: int = 10) -> float:
    xs = [float(v) for v in values]
    if len(xs) < 2:
        return 0.0
    lo, hi = min(xs), max(xs)
    if hi <= lo:
        return 0.0
    counts = [0] * bins
    for v in xs:
        idx = min(bins - 1, int((v - lo) / (hi - lo) * bins))
        counts[idx] += 1
    n = len(xs)
    ent = 0.0
    for cnt in counts:
        if cnt > 0:
            p = cnt / n
            ent -= p * math.log(p, 2)
    return ent
