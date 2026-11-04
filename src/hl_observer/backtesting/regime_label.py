"""IMPROVE-20 (#127) — ÉTIQUETER le régime d'un trade, sans jamais lire le futur.

POURQUOI CE MODULE EXISTE
-------------------------
`validation_gates.regime_robustness_gate` — le gate qui donne son sens au mot « robuste » dans la
recherche 150 M — cherche un champ `regime` sur chaque trade. **Personne ne l'écrivait jamais.**
Le gate retombait donc **en silence** sur des tranches de temps, et le « split par régime »
(IMPROVE-10, marqué *completed*) n'a jamais eu lieu.

C'est la 8e fois : *une capacité présente, un chaînon manquant, et personne qui se plaint.*

LA MINE QU'ON A DÉSAMORCÉE EN CHEMIN
------------------------------------
`garch11_variance` (la version historique) **lit le futur deux fois** : elle s'amorce sur la
variance de TOUTE la série, et elle publie `out[i]` APRÈS avoir vu `r[i]`. La brancher naïvement
aurait injecté du lookahead dans le gate anti-lookahead lui-même. On utilise donc ici
`garch11_variance_causale`.

LE SEUIL AUSSI PEUT MENTIR
--------------------------
Séparer « haute vol » et « basse vol » par la **médiane de tout l'échantillon** serait un lookahead
plus discret mais tout aussi réel : le seuil connaîtrait le test. Le seuil se calcule donc sur le
**TRAIN uniquement**, puis s'applique tel quel au test.

Aucune décision, aucun ordre : ce module ÉTIQUETTE. Quand il ne sait pas, il dit `INCONNU` —
il n'invente pas de label.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.regime_detection import garch11_variance_causale

HAUTE_VOL = "HAUTE_VOL"
BASSE_VOL = "BASSE_VOL"
INCONNU = "INCONNU"  # pas assez d'historique -> refus honnête, jamais un label fabriqué

WARMUP_DEFAUT = 20


@dataclass(frozen=True, slots=True)
class SeuilRegime:
    """Le seuil qui sépare les deux régimes, et d'où il vient.

    `n_train` est là pour qu'on ne puisse pas oublier sur quoi il a été calibré : un seuil sans
    provenance, c'est un chiffre qu'on finit par croire.
    """

    seuil: float
    n_train: int
    source: str = "median_variance_TRAIN"

    @property
    def fiable(self) -> bool:
        return self.n_train >= 10


def variances_causales(returns, *, warmup: int = WARMUP_DEFAUT) -> list:
    """Variance conditionnelle à chaque instant, calculée UNIQUEMENT sur le passé.

    Les `warmup` premières valent `None`. Un `None` est une information : « je ne sais pas encore ».
    """
    return garch11_variance_causale(returns, warmup=warmup)


def seuil_depuis_le_train(returns_train, *, warmup: int = WARMUP_DEFAUT) -> SeuilRegime | None:
    """Médiane des variances causales du TRAIN. Renvoie None si le train est trop court.

    🔴 Ne JAMAIS calculer ce seuil sur train+test : le seuil connaîtrait alors le futur, et le
    « split par régime » deviendrait un split par information privilégiée.
    """
    vs = [v for v in variances_causales(returns_train, warmup=warmup) if v is not None]
    if len(vs) < 10:
        return None
    vs.sort()
    n = len(vs)
    med = vs[n // 2] if n % 2 else 0.5 * (vs[n // 2 - 1] + vs[n // 2])
    return SeuilRegime(seuil=float(med), n_train=n)


def etiqueter(returns, seuil: SeuilRegime | None, *, warmup: int = WARMUP_DEFAUT) -> list[str]:
    """Un label par instant : HAUTE_VOL / BASSE_VOL / INCONNU.

    `etiqueter(...)[i]` ne dépend que de `returns[:i]` — c'est l'invariant que le test différentiel
    vérifie (modifier le futur ne doit changer AUCUN label passé).
    """
    if seuil is None or not seuil.fiable:
        return [INCONNU] * len(list(returns))
    out = []
    for v in variances_causales(returns, warmup=warmup):
        if v is None:
            out.append(INCONNU)
        else:
            out.append(HAUTE_VOL if v > seuil.seuil else BASSE_VOL)
    return out


def trades_etiquetes(trades: list[dict], labels: list[str]) -> list[dict]:
    """Pose le champ `regime` que `regime_robustness_gate` cherchait — et ne trouvait jamais.

    On ne modifie pas les trades en place : un trade est une observation, pas un brouillon.
    """
    if len(trades) != len(labels):
        raise ValueError(
            "trades (%d) et labels (%d) doivent être alignés 1-pour-1 : sinon on collerait "
            "le régime d'un trade sur un autre." % (len(trades), len(labels))
        )
    return [dict(t, regime=lab) for t, lab in zip(trades, labels)]


def freeze_regime_allowlist_from_train(
    train_rows: Sequence[Mapping[str, Any]],
    *,
    regime_field: str = "regime",
    gross_pnl_field: str = "gross_pnl_bps",
    cost_field: str = "cost_bps",
    min_trades_per_regime: int = 3,
    min_mean_net_bps: float = 0.0,
) -> dict[str, Any]:
    """Freeze regimes selected from TRAIN after explicit costs.

    This is a research gate, not an activation rule.  Every TRAIN row must have
    a finite gross result, a finite non-negative cost and a non-empty regime.
    Invalid evidence is rejected instead of being ignored or replaced by zero.
    The returned allow-list is frozen and can be applied to a later OOS split.
    """

    minimum = int(min_trades_per_regime)
    threshold = float(min_mean_net_bps)
    if minimum < 1 or not math.isfinite(threshold):
        raise ValueError("invalid TRAIN regime selection bounds")
    grouped: dict[str, list[float]] = {}
    invalid = 0
    for row in train_rows or ():
        if not isinstance(row, Mapping):
            invalid += 1
            continue
        regime = str(row.get(regime_field) or "").strip()
        try:
            gross = float(row.get(gross_pnl_field))
            cost = float(row.get(cost_field))
        except (TypeError, ValueError):
            invalid += 1
            continue
        if not regime or not math.isfinite(gross) or not math.isfinite(cost) or cost < 0:
            invalid += 1
            continue
        grouped.setdefault(regime, []).append(gross - cost)
    eligible = {
        regime: values
        for regime, values in grouped.items()
        if len(values) >= minimum and sum(values) / len(values) > threshold
    }
    return {
        "status": "TRAIN_REGIMES_FROZEN" if eligible else "NO_ELIGIBLE_TRAIN_REGIME",
        "allowed_regimes": sorted(eligible),
        "train_regime_counts": {regime: len(values) for regime, values in sorted(grouped.items())},
        "train_regime_mean_net_bps": {
            regime: round(sum(values) / len(values), 8)
            for regime, values in sorted(grouped.items())
        },
        "invalid_train_rows_rejected": invalid,
        "min_trades_per_regime": minimum,
        "min_mean_net_bps": threshold,
        "selection_scope": "TRAIN_ONLY_COSTED",
        "paper_read_only": True,
        "real_execution": False,
    }


def regime_ablation_receipt(
    train_rows: Sequence[Mapping[str, Any]],
    oos_rows: Sequence[Mapping[str, Any]],
    *,
    min_trades_per_regime: int = 3,
) -> dict[str, Any]:
    """Apply a TRAIN-frozen regime allow-list to a disjoint OOS sample."""
    frozen = freeze_regime_allowlist_from_train(
        train_rows,
        min_trades_per_regime=min_trades_per_regime,
    )
    allowed = set(frozen.get("allowed_regimes", ()))
    parsed = [row for row in oos_rows or () if isinstance(row, Mapping)]
    if any(not str(row.get("regime") or "").strip() for row in parsed):
        return {"status": "UNMEASURABLE", "reason": "OOS_REGIME_MISSING", "paper_read_only": True}
    selected = [row for row in parsed if str(row.get("regime")).strip() in allowed]
    status = "PROVEN" if frozen.get("status") == "TRAIN_REGIMES_FROZEN" and selected else "MORE_DATA"
    return {
        "status": status,
        "allowed_regimes": sorted(allowed),
        "oos_rows": len(parsed),
        "selected_oos_rows": len(selected),
        "selection_scope": "TRAIN_ONLY_COSTED",
        "costs_fixed_before_ablation": True,
        "paper_read_only": True,
        "real_execution": False,
    }


def vault_regime_resample_receipt(
    rows: Sequence[Mapping[str, Any]],
    *,
    vault_field: str = "vault",
    regime_field: str = "regime",
    value_field: str = "net_pnl_bps",
    n_resamples: int = 500,
    seed: int = 7,
) -> dict[str, Any]:
    """ECO-169 deterministic stratified resampling by vault and regime."""
    if isinstance(n_resamples, bool) or not isinstance(n_resamples, int) or n_resamples < 1:
        return {"status": "UNMEASURABLE", "reason": "invalid_resample_count", "paper_read_only": True}
    strata: dict[tuple[str, str], list[float]] = {}
    for row in rows or ():
        if not isinstance(row, Mapping):
            return {"status": "UNMEASURABLE", "reason": "invalid_row", "paper_read_only": True}
        vault = str(row.get(vault_field) or "").strip()
        regime = str(row.get(regime_field) or "").strip()
        try:
            value = float(row.get(value_field))
        except (TypeError, ValueError):
            return {"status": "UNMEASURABLE", "reason": "missing_value", "paper_read_only": True}
        if not vault or not regime or not math.isfinite(value):
            return {"status": "UNMEASURABLE", "reason": "invalid_stratum", "paper_read_only": True}
        strata.setdefault((vault, regime), []).append(value)
    if len(strata) < 2:
        return {"status": "MORE_DATA", "reason": "need_two_vault_regime_strata", "strata": len(strata), "paper_read_only": True}
    rng = random.Random(seed)
    means: list[float] = []
    keys = sorted(strata)
    for _ in range(n_resamples):
        values = [rng.choice(strata[key]) for key in keys]
        means.append(sum(values) / len(values))
    return {
        "status": "PROVEN", "verdict": "VAULT_REGIME_STRATIFIED_RESAMPLE",
        "strata": len(keys), "observations": sum(len(values) for values in strata.values()),
        "n_resamples": n_resamples, "seed": seed,
        "mean_of_resample_means": sum(means) / len(means),
        "paper_read_only": True, "real_execution": False,
    }


__all__ = [
    "HAUTE_VOL",
    "BASSE_VOL",
    "INCONNU",
    "SeuilRegime",
    "variances_causales",
    "seuil_depuis_le_train",
    "etiqueter",
    "trades_etiquetes",
    "freeze_regime_allowlist_from_train",
    "regime_ablation_receipt",
    "vault_regime_resample_receipt",
]
