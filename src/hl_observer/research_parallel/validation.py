"""LOT 7 — VALIDATION anti-sur-ajustement (Flo 25/07). Cœur PUR, testable sans réseau.

Tient compte de TOUTES les variantes testées (pas seulement la gagnante) :
  * DSR (Deflated Sharpe Ratio, Bailey & López de Prado) : déflate le Sharpe observé par le max attendu
    sous le nul quand on a essayé N variantes -> tue le « meilleur d'un grand nombre d'essais » ;
  * PBO (Probability of Backtest Overfitting, CSCV) : proba que la meilleure variante en IS soit sous la
    médiane en OOS -> mesure directe du sur-ajustement de sélection ;
  * dédup d'épisodes, 2 moitiés, leave-one-out, placebos direction/temps, walk-forward purgé (embargo).
  * mission/objective lock et validation aveugle : le candidat, l'objectif et les prémisses sont figés
    avant VALIDATION/OOS/FORWARD et les reviewers indépendants ne peuvent pas retuner après observation.
0 réseau, 0 ordre.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass, field
from itertools import combinations
from typing import Mapping

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


class ValidationIntegrityError(ValueError):
    """Fail-closed validation contract violation."""


@dataclass(frozen=True, slots=True)
class MissionContract:
    """Versioned user mission and KPI hierarchy frozen before validation."""

    mission_id: str
    version: str
    primary_metric: str
    kpi_hierarchy: tuple[str, ...]
    premises: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.mission_id or not self.version or not self.primary_metric:
            raise ValidationIntegrityError("MISSION_CONTRACT_INCOMPLETE")
        if not self.kpi_hierarchy:
            raise ValidationIntegrityError("KPI_HIERARCHY_INVALID")
        if not self.premises or len(set(self.premises)) != len(self.premises):
            raise ValidationIntegrityError("PREMISES_INVALID")

    def fingerprint(self) -> str:
        payload = {
            "mission_id": self.mission_id,
            "version": self.version,
            "primary_metric": self.primary_metric,
            "kpi_hierarchy": list(self.kpi_hierarchy),
            "premises": list(self.premises),
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class ObjectiveLock:
    """Immutable digest used by validators to reject objective/premise drift."""

    mission_id: str
    mission_version: str
    primary_metric: str
    kpi_hierarchy: tuple[str, ...]
    premises: tuple[str, ...]
    contract_sha256: str

    @classmethod
    def from_contract(cls, contract: MissionContract) -> "ObjectiveLock":
        return cls(
            contract.mission_id,
            contract.version,
            contract.primary_metric,
            contract.kpi_hierarchy,
            contract.premises,
            contract.fingerprint(),
        )

    def verify(self, contract: MissionContract) -> None:
        if contract.mission_id != self.mission_id:
            raise ValidationIntegrityError("MISSION_ID_DRIFT")
        if contract.version != self.mission_version:
            raise ValidationIntegrityError("MISSION_VERSION_DRIFT")
        if contract.primary_metric != self.primary_metric or contract.kpi_hierarchy != self.kpi_hierarchy:
            raise ValidationIntegrityError("OBJECTIVE_DRIFT")
        if contract.premises != self.premises:
            raise ValidationIntegrityError("PREMISE_DRIFT")
        if contract.fingerprint() != self.contract_sha256:
            raise ValidationIntegrityError("MISSION_CONTRACT_DRIFT")


def require_expected_objective(lock: ObjectiveLock, reported_metric: str) -> None:
    """Wrong-objective detector: a validator may only report the locked primary metric."""
    if reported_metric != lock.primary_metric:
        raise ValidationIntegrityError("WRONG_OBJECTIVE")


def require_premises(contract: MissionContract, evidence: Mapping[str, bool]) -> None:
    """Require every mission premise to have explicit positive evidence."""
    missing = [name for name in contract.premises if evidence.get(name) is not True]
    if missing:
        raise ValidationIntegrityError("PREMISE_NOT_PROVEN:" + ",".join(sorted(missing)))


_VALIDATION_STAGES = ("TRAIN_FROZEN", "VALIDATION", "OOS", "FORWARD")
_REQUIRED_REVIEW_ROLES = frozenset(
    {"quant_validator", "adversarial", "independent_reproducer", "forward_validator", "guardian"}
)


@dataclass(slots=True)
class ValidationFreeze:
    """Candidate freeze enforcing blind stage order and independent reviewers."""

    objective_lock: ObjectiveLock
    candidate_hash: str
    preregistration_id: str
    max_trials: int
    stage: str = "TRAIN_FROZEN"
    reviews: dict[str, str] = field(default_factory=dict)
    economic_verdict: str | None = None

    @classmethod
    def create(
        cls,
        contract: MissionContract,
        *,
        candidate_hash: str,
        preregistration_id: str,
        max_trials: int,
    ) -> "ValidationFreeze":
        if not candidate_hash or not preregistration_id or max_trials < 1:
            raise ValidationIntegrityError("VALIDATION_FREEZE_INCOMPLETE")
        return cls(ObjectiveLock.from_contract(contract), candidate_hash, preregistration_id, max_trials)

    def _require_candidate(self, candidate_hash: str) -> None:
        if candidate_hash != self.candidate_hash:
            raise ValidationIntegrityError("CANDIDATE_DRIFT")

    def advance(self, target_stage: str, *, candidate_hash: str) -> None:
        self._require_candidate(candidate_hash)
        if target_stage not in _VALIDATION_STAGES:
            raise ValidationIntegrityError("VALIDATION_STAGE_INVALID")
        current = _VALIDATION_STAGES.index(self.stage)
        target = _VALIDATION_STAGES.index(target_stage)
        if target != current + 1:
            raise ValidationIntegrityError("VALIDATION_STAGE_ORDER")
        self.stage = target_stage

    def record_review(self, role: str, *, reviewer_id: str, candidate_hash: str) -> None:
        self._require_candidate(candidate_hash)
        if self.stage not in {"OOS", "FORWARD"}:
            raise ValidationIntegrityError("REVIEW_BEFORE_BLIND_OOS")
        if role not in _REQUIRED_REVIEW_ROLES:
            raise ValidationIntegrityError("VALIDATOR_ROLE_INVALID")
        if not reviewer_id:
            raise ValidationIntegrityError("REVIEWER_ID_REQUIRED")
        if role in self.reviews:
            raise ValidationIntegrityError("VALIDATOR_ROLE_DUPLICATE")
        if reviewer_id in self.reviews.values():
            raise ValidationIntegrityError("REVIEWER_NOT_INDEPENDENT")
        self.reviews[role] = reviewer_id

    @property
    def independent_validation_complete(self) -> bool:
        return _REQUIRED_REVIEW_ROLES.issubset(self.reviews) and len(set(self.reviews.values())) == len(
            _REQUIRED_REVIEW_ROLES
        )

    def set_economic_verdict(self, verdict: str) -> None:
        if not verdict:
            raise ValidationIntegrityError("ECONOMIC_VERDICT_EMPTY")
        self.economic_verdict = verdict

    @property
    def technical_complete(self) -> bool:
        """Technical completion is independent of PASS/KILL/MORE_DATA economic outcome."""
        return self.stage == "FORWARD" and self.independent_validation_complete


@dataclass(slots=True)
class TrialBudget:
    """Counts every searched trial and implements preregistered early-stop limits."""

    max_trials: int
    max_consecutive_kills: int
    trials_seen: int = 0
    consecutive_kills: int = 0
    stop_reason: str | None = None

    def __post_init__(self) -> None:
        if self.max_trials < 1 or self.max_consecutive_kills < 1:
            raise ValidationIntegrityError("TRIAL_BUDGET_INVALID")

    @property
    def closed(self) -> bool:
        return self.stop_reason is not None

    def record(self, verdict: str) -> bool:
        if self.closed:
            raise ValidationIntegrityError("TRIAL_BUDGET_CLOSED")
        self.trials_seen += 1
        self.consecutive_kills = self.consecutive_kills + 1 if verdict == "KILL" else 0
        if self.consecutive_kills >= self.max_consecutive_kills:
            self.stop_reason = "CONSECUTIVE_KILLS"
        elif self.trials_seen >= self.max_trials:
            self.stop_reason = "MAX_TRIALS"
        return self.closed


__all__ = [
    "sharpe", "sharpe_max_attendu", "dsr", "pbo_cscv", "dedup_episodes", "placebo_direction",
    "walk_forward_purge", "ValidationIntegrityError", "MissionContract", "ObjectiveLock",
    "require_expected_objective", "require_premises", "ValidationFreeze", "TrialBudget",
]
