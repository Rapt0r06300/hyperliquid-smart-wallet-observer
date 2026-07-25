"""LOT 7 — VALIDATION anti-sur-ajustement (Flo 25/07). Cœur PUR, testable sans réseau.

Tient compte de TOUTES les variantes testées (pas seulement la gagnante) :
  * DSR (Deflated Sharpe Ratio, Bailey & López de Prado) : déflate le Sharpe observé par le max attendu
    sous le nul quand on a essayé N variantes -> tue le « meilleur d'un grand nombre d'essais » ;
  * PBO (Probability of Backtest Overfitting, CSCV) : proba que la meilleure variante en IS soit sous la
    médiane en OOS -> mesure directe du sur-ajustement de sélection ;
  * dédup d'épisodes, 2 moitiés, leave-one-out, placebos direction/temps, walk-forward purgé (embargo).
0 réseau, 0 ordre.
"""
from __future__ import annotations

import math
import statistics
from itertools import combinations

_GAMMA = 0.5772156649        # Euler-Mascheroni


def _phi(x):                 # CDF normale standard
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _phi_inv(p):             # quantile normal (approx. Acklam), p dans (0,1)
    if p <= 0:
        return -10.0
    if p >= 1:
        return 10.0
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00]
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= 1 - pl:
        q = p - 0.5; r = q*q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def sharpe(nets: list[float]) -> float:
    if len(nets) < 2:
        return 0.0
    sd = statistics.pstdev(nets)
    return (statistics.mean(nets) / sd) if sd > 1e-12 else 0.0


def sharpe_max_attendu(n_essais: int, var_sharpe: float) -> float:
    """E[max Sharpe] sous le nul pour n_essais variantes (Bailey-LdP). var_sharpe = variance des Sharpe
    across variantes. C'est la barre que le meilleur DOIT dépasser juste par chance."""
    if n_essais < 2 or var_sharpe <= 0:
        return 0.0
    z1 = _phi_inv(1 - 1.0 / n_essais)
    z2 = _phi_inv(1 - 1.0 / (n_essais * math.e))
    return math.sqrt(var_sharpe) * ((1 - _GAMMA) * z1 + _GAMMA * z2)


def dsr(nets: list[float], *, sharpes_essais: list[float]) -> dict:
    """DSR de la variante (ses `nets` par épisode) sachant les Sharpe de TOUTES les variantes essayées.
    DSR > 0,95 => significatif après déflation multi-essais."""
    T = len(nets)
    if T < 8:
        return {"dsr": None, "motif": "trop peu d'épisodes"}
    sr = sharpe(nets)
    var_sr = statistics.pvariance(sharpes_essais) if len(sharpes_essais) >= 2 else 0.0
    sr0 = sharpe_max_attendu(len(sharpes_essais), var_sr)
    sk = _skew(nets); ku = _kurt(nets)
    denom = math.sqrt(max(1e-9, 1 - sk * sr + (ku - 1) / 4.0 * sr * sr))
    dsr_val = _phi((sr - sr0) * math.sqrt(T - 1) / denom)
    return {"dsr": round(dsr_val, 4), "sr": round(sr, 4), "sr0_barre": round(sr0, 4),
            "n_essais": len(sharpes_essais), "significatif": dsr_val > 0.95}


def _skew(x):
    n = len(x); m = statistics.mean(x); sd = statistics.pstdev(x)
    return sum(((v - m) / sd) ** 3 for v in x) / n if sd > 1e-12 else 0.0


def _kurt(x):
    n = len(x); m = statistics.mean(x); sd = statistics.pstdev(x)
    return sum(((v - m) / sd) ** 4 for v in x) / n if sd > 1e-12 else 3.0


def pbo_cscv(perf: dict, *, s: int = 8) -> dict:
    """PBO par CSCV. `perf` = {variante: [net par bucket temporel]} (mêmes buckets alignés). On coupe le
    temps en s blocs, pour chaque combinaison de s/2 blocs en IS : la meilleure variante IS a-t-elle un
    rang OOS < médiane ? PBO = fraction de logits <= 0. Élevé => sélection sur-ajustée."""
    variantes = [v for v, arr in perf.items() if arr]
    if len(variantes) < 2:
        return {"pbo": None, "motif": "moins de 2 variantes"}
    m = min(len(perf[v]) for v in variantes)
    if m < s:
        s = max(2, m - (m % 2)) or 2
    if s < 2:
        return {"pbo": None, "motif": "trop peu de buckets"}
    blocs = [list(range(i * m // s, (i + 1) * m // s)) for i in range(s)]
    logits = []
    for combo in combinations(range(s), s // 2):
        idx_is = [i for b in combo for i in blocs[b]]
        idx_oos = [i for b in range(s) if b not in combo for i in blocs[b]]
        if not idx_is or not idx_oos:
            continue
        perf_is = {v: sum(perf[v][i] for i in idx_is) for v in variantes}
        best = max(perf_is, key=perf_is.get)
        oos_scores = sorted(((sum(perf[v][i] for i in idx_oos)), v) for v in variantes)
        rang = [v for _sc, v in oos_scores].index(best) + 1
        w = rang / (len(variantes) + 1.0)
        w = min(max(w, 1e-6), 1 - 1e-6)
        logits.append(math.log(w / (1 - w)))
    if not logits:
        return {"pbo": None, "motif": "aucune coupe"}
    pbo = sum(1 for l in logits if l <= 0) / len(logits)
    return {"pbo": round(pbo, 4), "n_coupes": len(logits), "sur_ajuste": pbo > 0.5}


def dedup_episodes(episodes: list[dict], *, fenetre_ms: float = 60_000.0) -> list[dict]:
    """Retire les épisodes trop rapprochés sur le MÊME coin+variante (événements non indépendants)."""
    vus: dict[tuple, float] = {}
    out = []
    for e in sorted(episodes, key=lambda x: x["ts_ms"]):
        cle = (e.get("coin"), e.get("variante"))
        if e["ts_ms"] - vus.get(cle, -1e18) < fenetre_ms:
            continue
        vus[cle] = e["ts_ms"]
        out.append(e)
    return out


def placebo_direction(episodes: list[dict]) -> float:
    """Baseline : mêmes entrées, SENS INVERSÉ. Un vrai edge directionnel doit battre son propre miroir."""
    return statistics.median([-e["net_bps"] for e in episodes]) if episodes else 0.0


def walk_forward_purge(episodes: list[dict], *, frac_train: float = 0.6, embargo_ms: float = 300_000.0):
    """Coupe train/test temporelle avec EMBARGO (purge) : aucun épisode test dans l'embargo après le train."""
    tri = sorted(episodes, key=lambda e: e["ts_ms"])
    if len(tri) < 4:
        return tri, []
    coupe = tri[int(len(tri) * frac_train)]["ts_ms"]
    train = [e for e in tri if e["ts_ms"] <= coupe]
    test = [e for e in tri if e["ts_ms"] > coupe + embargo_ms]
    return train, test


__all__ = ["sharpe", "sharpe_max_attendu", "dsr", "pbo_cscv", "dedup_episodes", "placebo_direction",
           "walk_forward_purge"]
