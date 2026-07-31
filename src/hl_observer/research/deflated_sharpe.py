"""ALPHA FIX-36 — DEFLATED SHARPE RATIO (Bailey & López de Prado) + Sharpe-max attendu sous sélection.

Un Sharpe « prometteur » ne prouve RIEN si on l'a choisi parmi des milliers d'essais : le maximum de N bruits
gaussiens dérive vers le haut. Le DSR déflate le Sharpe observé par (a) le Sharpe-max attendu sous l'hypothèse
nulle pour `n_trials` essais et leur dispersion, et (b) la non-normalité (skew/kurtosis) et la taille
d'échantillon. Il rend la PROBABILITÉ que le vrai Sharpe soit > 0 après correction de la sélection.

Anti-maquillage : entrées insuffisantes → None (jamais un DSR fabriqué). Pur, 0 réseau, 0 ordre réel.
Réf. : Bailey, López de Prado (2014), « The Deflated Sharpe Ratio ».
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Sequence

GAMMA_EM = 0.5772156649015329           # constante d'Euler–Mascheroni
_E = math.e


def _phi(x: float) -> float:
    """CDF normale standard Φ(x)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _phi_inv(p: float) -> float:
    """Inverse de la CDF normale (quantile), approximation d'Acklam (erreur < 1.15e-9)."""
    if p <= 0.0 or p >= 1.0:
        raise ValueError("p doit être dans ]0,1[")
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00)
    plow, phigh = 0.02425, 1.0 - 0.02425
    if p < plow:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1.0)
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1.0)


def sharpe_max_attendu(n_trials: int, var_sr_trials: float) -> float:
    """E[max] du Sharpe sous l'hypothèse nulle pour `n_trials` essais de variance `var_sr_trials` (Sharpe des
    essais). Croît avec le nombre d'essais → c'est le biais de sélection qu'il faut battre. n_trials≤1 → 0."""
    if n_trials <= 1 or var_sr_trials <= 0.0:
        return 0.0
    sigma = math.sqrt(var_sr_trials)
    n = float(n_trials)
    return sigma * ((1.0 - GAMMA_EM) * _phi_inv(1.0 - 1.0 / n) + GAMMA_EM * _phi_inv(1.0 - 1.0 / (n * _E)))


def deflated_sharpe(sr_observe: float, *, n_trials: int, var_sr_trials: float, n_obs: int,
                    skew: float = 0.0, kurt: float = 3.0) -> dict[str, float] | None:
    """DSR : probabilité que le vrai Sharpe > 0 APRÈS déflation pour la sélection sur `n_trials` essais.

    `sr_observe` et le résultat sont NON annualisés (par période, comme les votes). `kurt` = kurtosis brute
    (3 = normale). Promotion typique si dsr ≥ 0.95. Entrées insuffisantes → None (jamais fabriqué)."""
    if n_trials < 1 or n_obs < 2 or var_sr_trials < 0.0:
        return None
    sr_max = sharpe_max_attendu(n_trials, var_sr_trials)
    denom = math.sqrt(max(1e-12, 1.0 - skew * sr_observe + ((kurt - 1.0) / 4.0) * sr_observe ** 2))
    z = (sr_observe - sr_max) * math.sqrt(n_obs - 1.0) / denom
    return {"dsr": round(_phi(z), 6), "sr_max_attendu": round(sr_max, 6), "z": round(z, 4)}


def sharpe_depuis_votes(votes: Sequence[float]) -> float | None:
    """Sharpe (moyenne / écart-type population) d'une distribution de votes nets indépendants. None si <2
    votes ou dispersion nulle (Sharpe non défini — on ne fabrique pas l'infini)."""
    xs = [float(v) for v in votes if isinstance(v, (int, float)) and not isinstance(v, bool)]
    if len(xs) < 2:
        return None
    s = statistics.pstdev(xs)
    return round(statistics.mean(xs) / s, 6) if s > 0 else None


__all__ = ["sharpe_max_attendu", "deflated_sharpe", "sharpe_depuis_votes"]
