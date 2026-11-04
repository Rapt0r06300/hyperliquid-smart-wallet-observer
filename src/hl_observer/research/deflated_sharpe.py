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
from collections.abc import Mapping, Sequence
from typing import Any

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


def deflated_sharpe_all_attempts(
    attempts: Sequence[Mapping[str, Any]],
    *,
    candidate_id: str | None = None,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> dict[str, Any]:
    """Deflate a candidate Sharpe against every comparable search attempt.

    Each row must contain a unique ``attempt_id`` and a complete finite ``returns``
    sequence. All return vectors must have the same length; optional
    ``observation_ids`` must also match exactly across rows. If no candidate is
    specified, the highest raw Sharpe is selected deterministically, while every
    attempt remains in the multiple-testing distribution. Missing or invalid rows
    are visible and make the result ``UNMEASURABLE`` rather than being discarded.
    This is PAPER/read-only statistical evidence, not economic certification.
    """
    rows = list(attempts or [])
    base: dict[str, Any] = {
        "status": "UNMEASURABLE",
        "verdict": "INSUFFISANT",
        "reason": None,
        "n_attempts_total": len(rows),
        "n_trials": 0,
        "n_observations": 0,
        "candidate_id": None,
        "candidate_sharpe": None,
        "sharpes_by_attempt": {},
        "variance_sharpe_trials": None,
        "dsr": None,
        "sr_max_attendu": None,
        "z": None,
        "selection_source": "all_attempts",
        "real_execution": False,
    }
    if not rows:
        base["reason"] = "aucune_tentative"
        return base
    if candidate_id is not None and (not isinstance(candidate_id, str) or not candidate_id.strip()):
        base["reason"] = "candidate_id_invalide"
        return base
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value))
        for value in (skew, kurt)
    ):
        base["reason"] = "moments_non_finis"
        return base

    seen_ids: set[str] = set()
    sharpes: dict[str, float] = {}
    reference_observation_ids: tuple[Any, ...] | None = None
    observation_count: int | None = None
    invalid = False
    for row in rows:
        if not isinstance(row, Mapping):
            invalid = True
            continue
        attempt_key = row.get("attempt_id")
        returns = row.get("returns")
        if not isinstance(attempt_key, str) or not attempt_key.strip() or attempt_key in seen_ids:
            invalid = True
            continue
        seen_ids.add(attempt_key)
        if isinstance(returns, (str, bytes)) or not isinstance(returns, Sequence):
            invalid = True
            continue
        try:
            values = [float(value) for value in returns]
        except (TypeError, ValueError):
            invalid = True
            continue
        if len(values) < 2 or not all(math.isfinite(value) for value in values):
            invalid = True
            continue
        if observation_count is None:
            observation_count = len(values)
        elif len(values) != observation_count:
            invalid = True
            continue
        observation_ids = row.get("observation_ids")
        if observation_ids is not None:
            if isinstance(observation_ids, (str, bytes)) or not isinstance(observation_ids, Sequence):
                invalid = True
                continue
            ids = tuple(observation_ids)
            if len(ids) != len(values):
                invalid = True
                continue
            if reference_observation_ids is None:
                reference_observation_ids = ids
            elif ids != reference_observation_ids:
                invalid = True
                continue
        sharpe = sharpe_depuis_votes(values)
        if sharpe is None:
            invalid = True
            continue
        sharpes[attempt_key] = sharpe

    base["n_trials"] = len(sharpes)
    base["n_observations"] = observation_count or 0
    base["sharpes_by_attempt"] = dict(sharpes)
    if invalid or len(sharpes) != len(rows):
        base["reason"] = "tentatives_incompletes_ou_non_alignees"
        return base
    if len(sharpes) < 2 or not observation_count:
        base["reason"] = "distribution_insuffisante"
        return base
    chosen_id = candidate_id
    if chosen_id is None:
        chosen_id = max(sharpes, key=lambda key: (sharpes[key], -list(sharpes).index(key)))
    if chosen_id not in sharpes:
        base["reason"] = "candidate_absent"
        return base
    variance = statistics.pvariance(tuple(sharpes.values()))
    result = deflated_sharpe(
        sharpes[chosen_id],
        n_trials=len(sharpes),
        var_sr_trials=variance,
        n_obs=observation_count,
        skew=float(skew),
        kurt=float(kurt),
    )
    if result is None:
        base["reason"] = "deflation_non_mesurable"
        return base
    base.update(
        status="PROVEN",
        verdict="MESURE_STATISTIQUE",
        candidate_id=chosen_id,
        candidate_sharpe=sharpes[chosen_id],
        variance_sharpe_trials=round(variance, 12),
        dsr=result["dsr"],
        sr_max_attendu=result["sr_max_attendu"],
        z=result["z"],
    )
    return base


def deflated_sharpe_receipt(
    attempts: Sequence[Mapping[str, Any]],
    *,
    candidate_id: str | None = None,
) -> dict[str, Any]:
    """Stable ECO-163 entry point that counts every observed search attempt."""
    result = deflated_sharpe_all_attempts(attempts, candidate_id=candidate_id)
    result.update(contract="ECO-163-deflated-sharpe-all-attempts", paper_read_only=True, promotion="DISABLED_UNTIL_REVIEW")
    return result


__all__ = [
    "sharpe_max_attendu",
    "deflated_sharpe",
    "sharpe_depuis_votes",
    "deflated_sharpe_all_attempts",
    "deflated_sharpe_receipt",
]
