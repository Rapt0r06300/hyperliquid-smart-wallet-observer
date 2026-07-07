"""P2 — Optimiseur de configs sur replay, avec validation out-of-sample.

Distillé de passivbot (optimiseur) + freqtrade (walk-forward, anti-lookahead).
Cherche la meilleure config parmi des candidats en RÉUTILISANT les gardes déjà
présents (out_of_sample_guard, anti_overfit_guard) — pas de réécriture. Une config
n'est retenue que si elle tient hors échantillon (jamais l'overfit du train). Pur:
l'évaluateur de PF est injecté, aucune donnée inventée.
"""

from __future__ import annotations

from typing import Callable

from hl_observer.optimization.anti_overfit_guard import accept_config, degradation_ratio
from hl_observer.optimization.out_of_sample_guard import oos_split


def optimize_configs(
    candidates: list[dict],
    samples: list[dict],
    evaluate_pf: Callable[[dict, list[dict]], float],
    *,
    test_frac: float = 0.3,
    min_pf: float = 1.0,
    min_ratio: float = 0.5,
    ts_key: str = "ts_ms",
) -> dict:
    """Évalue chaque config en train/test temporel, retient celles qui généralisent.

    evaluate_pf(config, sample_subset) -> profit factor net (float).
    Retourne le classement des configs acceptées + le détail de chaque candidat.
    """

    train, test = oos_split(samples, test_frac=test_frac, ts_key=ts_key)
    rows: list[dict] = []
    for cfg in candidates or []:
        try:
            train_pf = float(evaluate_pf(cfg, train))
            test_pf = float(evaluate_pf(cfg, test))
        except Exception:
            rows.append({"config": cfg, "accepted": False, "reason": "EVAL_FAILED"})
            continue
        accepted = accept_config(train_pf, test_pf, min_pf=min_pf, min_ratio=min_ratio)
        rows.append({
            "config": cfg,
            "train_pf": round(train_pf, 4),
            "test_pf": round(test_pf, 4),
            "degradation_ratio": round(degradation_ratio(train_pf, test_pf), 4),
            "accepted": bool(accepted),
            "reason": "OOS_ROBUST" if accepted else "REJECTED_OVERFIT_OR_WEAK",
        })
    accepted = [r for r in rows if r.get("accepted")]
    accepted.sort(key=lambda r: -r["test_pf"])  # meilleur hors-échantillon d'abord
    return {
        "n_candidates": len(candidates or []),
        "n_accepted": len(accepted),
        "best": accepted[0] if accepted else None,
        "ranked_accepted": accepted,
        "all": rows,
        "honesty": "config retenue seulement si robuste hors échantillon; pas de promesse de PnL",
    }


__all__ = ["optimize_configs"]
