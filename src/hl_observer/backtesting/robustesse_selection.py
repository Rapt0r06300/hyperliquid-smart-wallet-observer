"""ROBUSTESSE DE SÉLECTION — rendre la recherche EXTRÊME sans en faire une machine à faux
gagnants (22/07, demande de Flo « trouve tous les meilleurs calibrages, extrême ET robuste »).

LE PIÈGE QUE CE MODULE FERME
----------------------------
Plus on essaie de configurations, plus la MEILLEURE d'entre elles a de chances d'être un
gagnant CHANCEUX — pas un edge. Une recherche à 1 420 essais qui ne pénalise pas le nombre
d'essais est une **fabrique d'artefacts**. La robustesse doit donc GRANDIR avec l'agressivité
de la recherche. Deux outils, tous deux standards de la littérature quant :

1. **PBO — Probability of Backtest Overfitting** (Bailey & López de Prado, 2014), via CSCV
   (Combinatorially-Symmetric Cross-Validation). On découpe la performance en S blocs
   temporels, on forme toutes les partitions IS/OOS de S/2 blocs, et pour chacune : la config
   la MEILLEURE en IS, à quel rang tombe-t-elle en OOS ? Si elle passe SOUS la médiane OOS,
   c'est une instance de sur-ajustement. **PBO = fraction de partitions sur-ajustées.**
   PBO ≈ 0 → la procédure GÉNÉRALISE ; PBO ≥ 0,5 → elle sur-ajuste, le « meilleur » est du bruit.

2. **Le seuil de bruit du multiple-testing** : avec N essais indépendants d'espérance nulle,
   le meilleur atteint déjà ≈ σ·√(2·ln N) par pur hasard. Un gagnant qui ne dépasse pas cette
   barre n'a rien prouvé — il a juste gagné à la loterie des N tirages.

Ce module ne PROMET aucun edge. Il REFUSE d'en déclarer un qui ne survit pas à ces deux tests.
Pur calcul sur une matrice de performances déjà mesurées : aucune donnée réseau, aucun ordre.
"""
from __future__ import annotations

import itertools
import json
import math
import random
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

#: au-dessus, la procédure de sélection sur-ajuste : le « meilleur » ne généralise pas.
PBO_SEUIL = 0.5
#: plafond de partitions IS/OOS évaluées (C(S,S/2) explose ; on échantillonne, graine fixe).
MAX_PARTITIONS = 2000
HARD_PLACEBO_DIMENSIONS = (
    "RANDOM_WALLET",
    "RANDOM_TIME",
    "RANDOM_DIRECTION",
    "COIN_MATCHED",
    "SAME_COSTS",
    "SAME_L2",
    "SAME_LATENCY",
)


@dataclass(frozen=True, slots=True)
class TrialRecord:
    trial_id: str
    hypothesis_id: str
    parameters_hash: str
    horizon: str
    coin: str
    regime: str
    state: str
    sharpe: float | None = None
    renamed_from: str | None = None
    recorded_at_ms: int = 0

    def normalized(self) -> "TrialRecord":
        return TrialRecord(
            trial_id=str(self.trial_id),
            hypothesis_id=str(self.hypothesis_id),
            parameters_hash=str(self.parameters_hash),
            horizon=str(self.horizon),
            coin=str(self.coin),
            regime=str(self.regime),
            state=str(self.state).upper(),
            sharpe=None if self.sharpe is None else float(self.sharpe),
            renamed_from=None if self.renamed_from is None else str(self.renamed_from),
            recorded_at_ms=int(self.recorded_at_ms or time.time() * 1000),
        )


class GlobalTrialRegistry:
    """Append-only registry: renamed and killed trials still count as attempts."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = None if path is None else Path(path)
        self._records: list[TrialRecord] = []

    def append(self, record: TrialRecord) -> TrialRecord:
        normalized = record.normalized()
        if any(existing.trial_id == normalized.trial_id for existing in self._records):
            raise ValueError(f"duplicate trial_id: {normalized.trial_id}")
        self._records.append(normalized)
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(asdict(normalized), sort_keys=True) + "\n")
        return normalized

    @property
    def n_trials(self) -> int:
        return len(self._records)

    @property
    def trial_sharpes(self) -> tuple[float, ...]:
        return tuple(record.sharpe for record in self._records if record.sharpe is not None)

    def hypothesis_attempts(self, hypothesis_id: str) -> int:
        return sum(record.hypothesis_id == hypothesis_id for record in self._records)


def _matrice_propre(matrice: Sequence[Sequence[float]]) -> tuple[list[list[float]], int]:
    """Nettoie la matrice [config][bloc] : lignes non vides, S bloc(s) PAIR commun. Rend (M, S)."""
    lignes = []
    for row in matrice or []:
        try:
            vals = [float(x) for x in row]
        except (TypeError, ValueError):
            continue
        if vals:
            lignes.append(vals)
    if len(lignes) < 2:
        return [], 0
    s = min(len(r) for r in lignes)
    s -= s % 2                                   # S doit être pair pour partitionner en 2 moitiés
    if s < 4:
        return [], s
    return [r[:s] for r in lignes], s


def pbo_cscv(matrice: Sequence[Sequence[float]], *, max_partitions: int = MAX_PARTITIONS,
             graine: int = 7) -> dict[str, Any]:
    """PBO par CSCV sur une matrice [config][bloc] de performance (plus haut = mieux).

    Rend {pbo, n_configs, n_blocs, n_partitions, lambda_median, verdict}. `pbo=None` si la
    matrice est trop maigre (< 2 configs ou < 4 blocs pairs) — INSUFFISANT, jamais un faux 0.
    """
    M, S = _matrice_propre(matrice)
    if not M:
        return {"pbo": None, "n_configs": len(matrice or []), "n_blocs": S,
                "verdict": "INSUFFISANT (< 2 configs ou < 4 blocs pairs)", "real_execution": False}
    N = len(M)
    if len({tuple(row) for row in M}) < 2:
        return {
            "pbo": None,
            "n_configs": N,
            "n_blocs": S,
            "n_partitions": 0,
            "verdict": "INSUFFISANT_CONFIGURATIONS_IDENTIQUES",
            "real_execution": False,
        }
    blocs = list(range(S))
    partitions = list(itertools.combinations(blocs, S // 2))
    if len(partitions) > max_partitions:
        partitions = random.Random(graine).sample(partitions, max_partitions)
    n_surajuste = 0
    lambdas: list[float] = []
    for IS in partitions:
        ens_is = set(IS)
        OOS = [b for b in blocs if b not in ens_is]
        perf_is = [sum(M[i][b] for b in IS) for i in range(N)]
        perf_oos = [sum(M[i][b] for b in OOS) for i in range(N)]
        best_is = max(perf_is)
        winners = [index for index, value in enumerate(perf_is) if value == best_is]
        # Conservative tie handling: retain the worst OOS member of the IS tie.
        n_star = min(winners, key=lambda index: perf_oos[index])
        val = perf_oos[n_star]
        lower = sum(1 for value in perf_oos if value < val)
        equal = sum(1 for value in perf_oos if value == val)
        rang = lower + (equal + 1.0) / 2.0
        omega = min(max(rang / (N + 1), 1e-6), 1 - 1e-6)          # rang relatif dans (0,1)
        lam = math.log(omega / (1 - omega))                       # logit : <0 => sous la médiane OOS
        lambdas.append(lam)
        if lam < 0:
            n_surajuste += 1
    pbo = n_surajuste / len(partitions)
    return {"pbo": round(pbo, 4), "n_configs": N, "n_blocs": S, "n_partitions": len(partitions),
            "lambda_median": round(statistics.median(lambdas), 4),
            "verdict": "SUR_AJUSTE" if pbo > PBO_SEUIL else "ROBUSTE", "real_execution": False}


def seuil_bruit_multiple_testing(n_essais: int, sigma: float) -> float:
    """La performance qu'atteint DÉJÀ le meilleur de `n_essais` tirages d'espérance nulle, par
    pur hasard : σ·√(2·ln N). Un gagnant qui ne la dépasse pas n'a rien prouvé."""
    n = max(int(n_essais or 0), 2)
    return float(sigma) * math.sqrt(2.0 * math.log(n))


def verdict_robustesse(matrice: Sequence[Sequence[float]], n_essais: int, *,
                       net_gagnant: float | None = None, sigma_null: float | None = None,
                       max_partitions: int = MAX_PARTITIONS) -> dict[str, Any]:
    """Le verdict combiné : ROBUSTE seulement si (PBO <= 0,5) ET (le gagnant bat le seuil de
    bruit du multiple-testing, quand on peut le calculer). DENY-BY-DEFAULT : un PBO incalculable
    n'est jamais 'robuste'."""
    res = pbo_cscv(matrice, max_partitions=max_partitions)
    res["n_essais"] = int(n_essais or 0)
    robuste = (res.get("pbo") is not None) and (res["pbo"] <= PBO_SEUIL)
    if net_gagnant is not None and sigma_null:
        seuil = seuil_bruit_multiple_testing(n_essais, sigma_null)
        res["seuil_bruit"] = round(seuil, 6)
        res["bat_le_bruit"] = bool(net_gagnant > seuil)
        robuste = robuste and res["bat_le_bruit"]
    res["robuste"] = bool(robuste)
    if res.get("pbo") is None:
        res["verdict"] = "INSUFFISANT"
    elif not robuste and res.get("verdict") == "ROBUSTE":
        res["verdict"] = "SUR_AJUSTE"          # le PBO passe mais le bruit non -> pas robuste
    return res


__all__ = [
    "PBO_SEUIL",
    "MAX_PARTITIONS",
    "HARD_PLACEBO_DIMENSIONS",
    "TrialRecord",
    "GlobalTrialRegistry",
    "pbo_cscv",
    "seuil_bruit_multiple_testing",
    "verdict_robustesse",
]
