"""Offline Copy-Vault Discovery tournament on canonical PAPER replay rows.

The tournament ranks causal, pre-outcome filters on the same executable trades and
cost model. It is TRAIN-only and can never emit a freeze verdict. Missing feature
surfaces fail closed so an attractive PnL cannot hide unavailable causal evidence.
"""
from __future__ import annotations

import json
import math
from collections import Counter, deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.backtesting.train_statistics import summarize_train_rows

ROOT = Path(__file__).resolve().parents[1]
RAW_REPORT = ROOT / "runtime" / "reports" / "economic_campaigns" / "raw" / "copy_vault.json"

MECHANISM_FEATURES = {
    "EXIT_HAZARD": "feature_fill_count",
    "INDEPENDENT_CONSENSUS": "feature_prior_consensus",
    "BURST_ACCELERATION": "feature_burst_rate_hz",
    "EXECUTION_EFFICIENCY": "feature_execution_efficiency",
    "CAPACITY_SLACK": "entry_capacity_usd",
    "L2_STATE_INTERACTION": "feature_l2_state_quality",
    "DEVIATION_REENTRY": "feature_price_deviation_reentry",
    "CROSS_VENUE_ANTICIPATION": "feature_cross_venue_lead_ms",
    "TOXICITY_VETO": "feature_prior_vault_mean_net",
    "ROTATION_FLOW": "feature_rotation",
    "REGIME_PERSISTENCE": "feature_prior_vault_mean_net",
    "NET_EXPOSURE_IMBALANCE": "feature_prior_consensus",
    "FUNDING_CONTEXT": "feature_funding_context",
}

_CACHE: tuple[int, list[dict[str, Any]]] | None = None


def _number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _metaorder_feature_index() -> dict[str, dict[str, float]]:
    """Rebuild causal prefix features from the canonical Copy-Vault loader once."""

    from hl_observer.backtesting.copy_vault_causal_selection import cluster_metaorders
    from tools import pipeline_copie_reel

    entries, _audit = pipeline_copie_reel.charger_entrees_alpha_avec_audit(ROOT)
    metaorders, _meta_audit = cluster_metaorders(entries)
    result: dict[str, dict[str, float]] = {}
    for row in metaorders:
        identity = str(row.get("metaorder_id") or "")
        members = [item for item in (row.get("member_events") or []) if isinstance(item, Mapping)]
        observed = [int(item.get("observed_at_ms") or 0) for item in members]
        observed = [value for value in observed if value > 0]
        sizes = [float(item.get("taille_usd") or 0.0) for item in members]
        duration_seconds = (max(observed) - min(observed)) / 1_000.0 if len(observed) >= 2 else 0.0
        result[identity] = {
            "feature_fill_count": float(len(members)),
            "feature_burst_rate_hz": (
                float(max(0, len(observed) - 1)) / duration_seconds
                if duration_seconds > 0.0
                else 0.0
            ),
            "feature_size_acceleration": (
                sizes[-1] / sizes[0] if sizes and sizes[0] > 0.0 else 0.0
            ),
            "feature_leader_notional_usd": float(row.get("leader_notional_usd") or 0.0),
            "feature_move_fraction": float(row.get("move_frac_audit_sum") or 0.0),
        }
    return result


def _enrich(
    rows: Sequence[Mapping[str, Any]],
    *,
    metaorder_features: Mapping[str, Mapping[str, float]] | None = None,
) -> list[dict[str, Any]]:
    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (int(row.get("signal_ts_ms") or 0), str(row.get("trade_id") or "")),
    )
    recent: deque[dict[str, Any]] = deque()
    previous_by_vault: dict[str, dict[str, Any]] = {}
    enriched: list[dict[str, Any]] = []
    for row in ordered:
        signal_ts = int(row.get("signal_ts_ms") or 0)
        vault = str(row.get("vault") or "").lower()
        coin = str(row.get("coin") or "").upper()
        direction = int(row.get("direction") or 0)
        while recent and signal_ts - int(recent[0].get("signal_ts_ms") or 0) > 300_000:
            recent.popleft()
        consensus = len(
            {
                str(prior.get("vault") or "").lower()
                for prior in recent
                if str(prior.get("coin") or "").upper() == coin
                and int(prior.get("direction") or 0) == direction
                and str(prior.get("vault") or "").lower() != vault
            }
        )
        previous = previous_by_vault.get(vault)
        rotation = bool(
            previous
            and str(previous.get("coin") or "").upper() != coin
            and 0 < signal_ts - int(previous.get("signal_ts_ms") or 0) <= 3_600_000
        )
        prior_closed = [
            value
            for prior in ordered
            if str(prior.get("vault") or "").lower() == vault
            and 0 < int(prior.get("exit_ts_ms") or 0) < signal_ts
            and (value := _number(prior.get("net_pnl_usd"))) is not None
        ]
        latency = _number(row.get("observed_latency_ms"))
        spread = _number(row.get("regime_reference_spread_bps"))
        notional = _number(row.get("notional_usd"))
        entry_capacity = _number(row.get("entry_capacity_usd"))
        capacity_slack = (
            entry_capacity / notional
            if entry_capacity is not None
            and notional is not None
            and float(notional) > 0.0
            else None
        )
        execution_efficiency = (
            capacity_slack / (1.0 + max(0.0, float(latency)) / 1_000.0)
            if capacity_slack is not None and latency is not None
            else None
        )
        l2_quality = (
            capacity_slack / (1.0 + max(0.0, float(spread)))
            if capacity_slack is not None and spread is not None
            else None
        )
        enriched_row = {
            **row,
            **dict((metaorder_features or {}).get(str(row.get("metaorder_id") or ""), {})),
            "feature_prior_consensus": float(consensus),
            "feature_rotation": 1.0 if rotation else 0.0,
            "feature_prior_vault_mean_net": (
                sum(prior_closed) / len(prior_closed) if prior_closed else None
            ),
            "feature_execution_efficiency": execution_efficiency,
            "feature_l2_state_quality": l2_quality,
        }
        enriched.append(enriched_row)
        recent.append(row)
        previous_by_vault[vault] = row
    return enriched


def _load_rows() -> list[dict[str, Any]]:
    global _CACHE
    stat = RAW_REPORT.stat()
    stamp = int(stat.st_mtime_ns)
    if _CACHE is not None and _CACHE[0] == stamp:
        return _CACHE[1]
    payload = json.loads(RAW_REPORT.read_text(encoding="utf-8"))
    trades = payload.get("trades") if isinstance(payload, Mapping) else None
    if not isinstance(trades, list):
        raise RuntimeError("canonical Copy-Vault raw report has no trades")
    rows = _enrich(
        [row for row in trades if isinstance(row, Mapping)],
        metaorder_features=_metaorder_feature_index(),
    )
    _CACHE = (stamp, rows)
    return rows


def evaluate_feature_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    mechanism: str,
    keep_fraction: float,
    family_trial_count: int,
) -> dict[str, Any]:
    """Rank a causal feature and summarize TRAIN economics without certifying it."""

    feature = MECHANISM_FEATURES.get(str(mechanism))
    train = [dict(row) for row in rows if str(row.get("walk_forward_segment") or "").lower() == "train"]
    available = [
        row for row in train if feature and _number(row.get(feature)) is not None
    ]
    if not feature or not available:
        return {
            "candidate_verdict": "REJECT",
            "candidate_reasons": ["FEATURE_UNAVAILABLE"],
            "mechanism": str(mechanism),
            "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
            "heldout_evaluated": False,
            "sample_count": 0,
            "net_usd": 0.0,
            "pf": 0.0,
            "family_trial_count": int(family_trial_count),
        }
    fraction = min(1.0, max(0.05, float(keep_fraction)))
    keep = max(1, math.ceil(len(available) * fraction))
    selected = sorted(
        available,
        key=lambda row: (
            -float(row[feature]),
            int(row.get("signal_ts_ms") or 0),
            str(row.get("trade_id") or ""),
        ),
    )[:keep]
    selected.sort(key=lambda row: int(row.get("signal_ts_ms") or 0))
    net_values = [float(row.get("net_pnl_usd") or 0.0) for row in selected]
    gross = sum(float(row.get("gross_pnl_usd") or 0.0) for row in selected)
    costs = gross - sum(net_values)
    gains = sum(value for value in net_values if value > 0.0)
    losses = -sum(value for value in net_values if value < 0.0)
    pf = gains / losses if losses > 0.0 else (999.0 if gains > 0.0 else 0.0)
    equity = drawdown = peak = 0.0
    for value in net_values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    stats = summarize_train_rows(
        selected,
        value_key="net_pnl_usd",
        timestamp_key="signal_ts_ms",
        trial_count=max(1, int(family_trial_count)),
    )
    timestamps = [int(row.get("signal_ts_ms") or 0) for row in selected]
    span_seconds = (max(timestamps) - min(timestamps)) / 1_000.0 if len(timestamps) >= 2 else 0.0
    daily_net = sum(net_values) / (span_seconds / 86_400.0) if span_seconds >= 86_400.0 else None
    vault_counts = Counter(str(row.get("vault") or "") for row in selected)
    coin_counts = Counter(str(row.get("coin") or "") for row in selected)
    reasons: list[str] = ["TOURNAMENT_ONLY_NOT_FREEZE_EVIDENCE"]
    if len(selected) < 8:
        reasons.append("INSUFFICIENT_TRAIN_SAMPLE")
    if int(stats.get("distinct_days") or 0) < 3:
        reasons.append("INSUFFICIENT_DISTINCT_DAYS")
    if daily_net is None:
        reasons.append("DAILY_RATE_UNMEASURABLE")
    elif daily_net < 4.0:
        reasons.append("NET_HEADROOM_BELOW_TARGET")
    if float(stats.get("total_lcb_usd") or 0.0) <= 0.0:
        reasons.append("MULTIPLICITY_ADJUSTED_LCB_NOT_POSITIVE")
    promising = not any(
        reason in reasons
        for reason in (
            "INSUFFICIENT_TRAIN_SAMPLE",
            "INSUFFICIENT_DISTINCT_DAYS",
            "DAILY_RATE_UNMEASURABLE",
            "NET_HEADROOM_BELOW_TARGET",
            "MULTIPLICITY_ADJUSTED_LCB_NOT_POSITIVE",
        )
    )
    return {
        "candidate_verdict": "ITERATE" if promising else "REJECT",
        "candidate_reasons": reasons,
        "mechanism": str(mechanism),
        "feature": feature,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_evaluated": False,
        "paper_read_only": True,
        "real_execution": False,
        "sample_count": len(selected),
        "distinct_days": int(stats.get("distinct_days") or 0),
        "net_usd": round(sum(net_values), 8),
        "daily_net_usd": round(daily_net, 8) if daily_net is not None else None,
        "target_headroom_usd_per_day": round(daily_net - 4.0, 8) if daily_net is not None else None,
        "gross_usd": round(gross, 8),
        "costs_usd": round(costs, 8),
        "pf": round(pf, 8),
        "max_drawdown_usd": round(drawdown, 8),
        "roi": round(sum(net_values) / max(1.0, sum(float(row.get("notional_usd") or 0.0) for row in selected)), 8),
        "largest_vault_share": max(vault_counts.values(), default=0) / len(selected),
        "largest_coin_share": max(coin_counts.values(), default=0) / len(selected),
        "concentration": max(vault_counts.values(), default=0) / len(selected),
        "capacity": min(
            (float(row.get("entry_capacity_usd") or 0.0) for row in selected), default=0.0
        ),
        "family_trial_count": int(family_trial_count),
        "multiplicity_adjusted_lcb_usd": stats.get("total_lcb_usd"),
        "selected_trade_ids": [str(row.get("trade_id") or "") for row in selected],
    }


def evaluate(
    params: Mapping[str, Any], *, budget: float = 1.0, context: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    rows = _load_rows()
    ordered = sorted(rows, key=lambda row: int(row.get("signal_ts_ms") or 0))
    prefix_count = max(1, math.ceil(len(ordered) * min(1.0, max(0.05, float(budget)))))
    cost_model = context.get("cost_model") if isinstance(context, Mapping) else {}
    family_trial_count = (
        int(cost_model.get("family_trial_count") or 1)
        if isinstance(cost_model, Mapping)
        else 1
    )
    return evaluate_feature_rows(
        ordered[:prefix_count],
        mechanism=str(params.get("mechanism") or ""),
        keep_fraction=float(params.get("keep_fraction") or 0.5),
        family_trial_count=family_trial_count,
    )


__all__ = ["MECHANISM_FEATURES", "evaluate", "evaluate_feature_rows"]
