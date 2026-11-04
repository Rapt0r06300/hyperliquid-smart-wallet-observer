"""ALPHA P40 — WALLET INFORMATION RATIO : score d'un wallet selon ce qui compte POUR NOUS, jamais son PnL brut.

Combine : temps d'avance (lead time), edge copyable gross, décroissance de l'edge, capacité, tolérance à la
latence, stabilité coin/jour/régime, indépendance d'entité. Un wallet au gros PnL mais non copyable (latence,
capacité, decay) score bas. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from statistics import median
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def info_ratio(*, lead_time_ms: Any, copyable_gross_bps: Any, edge_decay_ratio: Any = 0.0,
               capacity_usd: Any = None, latency_tol_ms: Any = None, stability: Any = 0.5,
               entity_independent: bool = True, cout_bps: float = 9.0) -> dict[str, Any]:
    """Score ∈ [0,1] (0 = inutile). Requiert lead_time et copyable_gross ; le reste module."""
    if not isinstance(lead_time_ms, (int, float)) or not isinstance(copyable_gross_bps, (int, float)):
        return {"score": UNMEASURABLE, "raison": "lead_time/copyable manquant"}
    net = copyable_gross_bps - cout_bps
    if net <= 0:
        return {"score": 0.0, "net_copyable_bps": round(net, 4), "raison": "net copyable <= 0"}
    # normalisations douces
    s_lead = _clamp01(lead_time_ms / 2000.0)                 # 2s d'avance = plein pot
    s_net = _clamp01(net / 20.0)                             # 20 bps net = plein pot
    s_decay = _clamp01(1.0 - float(edge_decay_ratio))        # decay fort -> pénalité
    s_stab = _clamp01(float(stability))
    s_cap = _clamp01((float(capacity_usd) / 1000.0)) if isinstance(capacity_usd, (int, float)) else 0.5
    s_lat = _clamp01(float(latency_tol_ms) / 1000.0) if isinstance(latency_tol_ms, (int, float)) else 0.5
    penal_entite = 1.0 if entity_independent else 0.4
    score = (0.30 * s_net + 0.20 * s_lead + 0.15 * s_decay + 0.15 * s_stab +
             0.10 * s_cap + 0.10 * s_lat) * penal_entite
    return {"score": round(score, 4), "net_copyable_bps": round(net, 4),
            "composantes": {"net": s_net, "lead": s_lead, "decay": s_decay, "stab": s_stab,
                            "cap": s_cap, "lat": s_lat, "entite": penal_entite}}


def classer(wallets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classe des wallets par info_ratio décroissant (les scores UNMEASURABLE en dernier)."""
    def cle(w: dict[str, Any]) -> float:
        s = w.get("score")
        return -s if isinstance(s, (int, float)) else 1e9
    return sorted(wallets, key=cle)


def compare_markout_to_pnl_score(
    train_rows: Sequence[Mapping[str, Any]],
    oos_rows: Sequence[Mapping[str, Any]],
    *,
    cutoff_ms: int,
    min_rows_per_bucket: int = 3,
    markout_field: str = "leader_markout_score_bps",
    pnl_score_field: str = "pnl_score_bps",
    outcome_field: str = "realized_net_pnl_bps",
    signal_ts_field: str = "signal_ts_ms",
    episode_id_field: str = "episode_id",
) -> dict[str, Any]:
    """Compare two frozen predictors against the same OOS realized outcome.

    Medians are learned from TRAIN only.  OOS outcomes are never used to choose
    a threshold, and missing or future-split evidence fails closed.  The PnL
    score is treated as a baseline predictor, not as proof that prior
    profitability is causal.
    """

    if isinstance(cutoff_ms, bool) or not isinstance(cutoff_ms, int) or cutoff_ms <= 0:
        return {"status": "UNMEASURABLE", "reason": "INVALID_CUTOFF", "paper_read_only": True}
    minimum = int(min_rows_per_bucket)
    if minimum < 1:
        return {"status": "UNMEASURABLE", "reason": "INVALID_MINIMUM", "paper_read_only": True}

    def _parse(rows: Sequence[Mapping[str, Any]], *, train: bool) -> tuple[list[dict[str, float]], str | None]:
        parsed: list[dict[str, float]] = []
        seen: set[str] = set()
        for row in rows or ():
            if not isinstance(row, Mapping):
                return [], "INVALID_ROW"
            episode = str(row.get(episode_id_field) or "").strip()
            ts = row.get(signal_ts_field)
            try:
                markout = float(row.get(markout_field))
                pnl_score = float(row.get(pnl_score_field))
                outcome = float(row.get(outcome_field))
            except (TypeError, ValueError):
                return [], "MISSING_SCORE_OR_OUTCOME"
            if (
                not episode
                or episode in seen
                or isinstance(ts, bool)
                or not isinstance(ts, int)
                or ts <= 0
                or (train and ts > cutoff_ms)
                or (not train and ts <= cutoff_ms)
                or any(not math.isfinite(value) for value in (markout, pnl_score, outcome))
            ):
                return [], "INVALID_SPLIT_OR_DUPLICATE_EPISODE"
            seen.add(episode)
            parsed.append({"markout": markout, "pnl_score": pnl_score, "outcome": outcome})
        return parsed, None

    train, train_error = _parse(train_rows, train=True)
    oos, oos_error = _parse(oos_rows, train=False)
    if train_error or oos_error or not train or not oos:
        return {
            "status": "UNMEASURABLE",
            "reason": train_error or oos_error or "EMPTY_SPLIT",
            "paper_read_only": True,
            "real_execution": False,
        }

    markout_threshold = float(median(row["markout"] for row in train))
    pnl_threshold = float(median(row["pnl_score"] for row in train))

    def _buckets(field: str, threshold: float) -> dict[str, Any]:
        high = [row["outcome"] for row in oos if row[field] >= threshold]
        low = [row["outcome"] for row in oos if row[field] < threshold]

        def _metric(values: list[float]) -> dict[str, Any]:
            if not values:
                return {"rows": 0, "mean_outcome_bps": None}
            return {"rows": len(values), "mean_outcome_bps": round(sum(values) / len(values), 8)}

        return {"threshold_train": threshold, "high": _metric(high), "low": _metric(low)}

    markout = _buckets("markout", markout_threshold)
    pnl_score = _buckets("pnl_score", pnl_threshold)
    comparable = all(
        bucket[side]["rows"] >= minimum
        for bucket in (markout, pnl_score)
        for side in ("high", "low")
    )
    return {
        "status": "COMPARABLE" if comparable else "UNMEASURABLE",
        "reason": None if comparable else "INSUFFICIENT_OOS_BUCKET_SAMPLE",
        "cutoff_ms": cutoff_ms,
        "train_rows": len(train),
        "oos_rows": len(oos),
        "markout_predictor": markout,
        "pnl_score_predictor": pnl_score,
        "threshold_scope": "TRAIN_ONLY",
        "same_oos_outcome": True,
        "prior_profitability_not_causal_claim": True,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
    }


__all__ = ["info_ratio", "classer", "compare_markout_to_pnl_score", "UNMEASURABLE"]
