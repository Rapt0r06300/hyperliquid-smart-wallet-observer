"""Copy-Vault v8c TRAIN-only: causal entry efficiency plus risk budgets.

The fixed v5 lifecycle signal is ranked only with information known when the
paper entry becomes executable: visible entry capacity, paper notional and the
elapsed signal-to-entry delay.  A threshold learned inside TRAIN is combined
with chronological vault/day and coin/day budgets.  Outcomes and exit-book
state never participate in admission.

PAPER/READ-ONLY.  This module imports no exchange or order client.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.copy_vault_executable import (
    select_observed_continuations,
    temporal_bounds,
)
from hl_observer.backtesting.copy_vault_protocol import COPY_DELAY_MS, MAX_TARGET_LAG_MS
from hl_observer.backtesting.copy_vault_v4_train import assess_train_variant
from hl_observer.backtesting.copy_vault_v5_lifecycle_train import replay_lifecycle_train
from hl_observer.backtesting.copy_vault_v6_balanced_train import (
    apply_causal_daily_risk_budget,
)
from hl_observer.backtesting.train_statistics import stable_hash

SCHEMA_VERSION = "hypersmart.copy_vault_v8_entry_efficiency_train.v1"
MECHANISM = "copy_vault_v8c_causal_entry_efficiency_risk_budget"
PARENT_REQUIRED_OBSERVED_FILLS = 2
PARENT_MAX_HOLD_MS = 3_600_000
KEEP_FRACTIONS = (0.25, 0.40, 0.50, 0.65)
VAULT_DAILY_LIMITS = (1, 2)
COIN_DAILY_LIMIT = 1
PRIOR_FAMILY_TRIAL_COUNT = 96
NEW_TRIAL_COUNT = len(KEEP_FRACTIONS) * len(VAULT_DAILY_LIMITS)
BONFERRONI_TRIAL_COUNT = PRIOR_FAMILY_TRIAL_COUNT + NEW_TRIAL_COUNT


def _finite_number(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def entry_efficiency_score(row: Mapping[str, Any]) -> float | None:
    """Return a dimensionless score using only decision-time fields."""

    capacity = _finite_number(row.get("entry_capacity_usd"))
    notional = _finite_number(row.get("notional_usd"))
    try:
        entry_ms = int(row.get("entry_ts_ms") or 0)
        signal_ms = int(row.get("signal_ts_ms") or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    delay_ms = entry_ms - signal_ms
    if (
        capacity is None
        or notional is None
        or capacity <= 0.0
        or notional <= 0.0
        or signal_ms <= 0
        or delay_ms < 0
    ):
        return None
    return (capacity / notional) / (1.0 + delay_ms / 1_000.0)


def select_entry_efficiency(
    trades: Sequence[Mapping[str, Any]],
    *,
    keep_fraction: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Learn a TRAIN threshold without reading outcomes or exit state."""

    fraction = float(keep_fraction)
    if not 0.0 < fraction <= 1.0:
        raise ValueError("keep_fraction must be in (0, 1]")
    scored: list[tuple[float, dict[str, Any]]] = []
    rejected = 0
    for raw in trades:
        row = dict(raw)
        score = entry_efficiency_score(row)
        if score is None:
            rejected += 1
            continue
        scored.append((score, row))
    scored.sort(
        key=lambda item: (
            -item[0],
            int(item[1].get("entry_ts_ms") or 0),
            str(item[1].get("trade_id") or ""),
        )
    )
    keep = max(1, math.ceil(len(scored) * fraction)) if scored else 0
    threshold = scored[keep - 1][0] if keep else None
    selected = [
        {
            **row,
            "entry_efficiency_score": score,
            "entry_efficiency_threshold": threshold,
            "entry_efficiency_keep_fraction": fraction,
            "entry_efficiency_uses_outcome": False,
            "entry_efficiency_uses_exit_state": False,
        }
        for score, row in scored
        if threshold is not None and score >= threshold
    ]
    selected.sort(
        key=lambda row: (
            int(row.get("entry_ts_ms") or 0),
            str(row.get("trade_id") or ""),
        )
    )
    return selected, {
        "input_trades": len(trades),
        "scored_trades": len(scored),
        "invalid_entry_feature_rejected": rejected,
        "requested_keep_fraction": fraction,
        "requested_keep_count": keep,
        "selected_with_threshold_ties": len(selected),
        "learned_entry_efficiency_threshold": threshold,
        "feature_fields": [
            "entry_capacity_usd",
            "notional_usd",
            "signal_ts_ms",
            "entry_ts_ms",
        ],
    }


def _signal_ids(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    return {str(row.get("metaorder_id") or "") for row in rows if row.get("metaorder_id")}


def explore_copy_vault_v8_entry_efficiency_train(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, Sequence[Mapping[str, Any]]],
    leader_events: Sequence[Mapping[str, Any]],
    *,
    input_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate the predeclared 4 x 2 admission grid on TRAIN only."""

    continuations, continuation_audit = select_observed_continuations(
        metaorders,
        required_observed_fills=PARENT_REQUIRED_OBSERVED_FILLS,
    )
    bounds = temporal_bounds(
        continuations,
        purge_ms=COPY_DELAY_MS + PARENT_MAX_HOLD_MS + MAX_TARGET_LAG_MS,
    )
    train_start_ms = bounds.get("train_start_ms")
    train_end_ms = bounds.get("train_end_ms")
    valid_bounds = bool(
        train_start_ms is not None
        and train_end_ms is not None
        and int(train_end_ms) >= int(train_start_ms)
    )
    if valid_bounds:
        parent_trades, parent_audit = replay_lifecycle_train(
            metaorders,
            books_by_coin,
            leader_events,
            required_observed_fills=PARENT_REQUIRED_OBSERVED_FILLS,
            horizon_ms=PARENT_MAX_HOLD_MS,
            train_start_ms=int(train_start_ms),
            train_end_ms=int(train_end_ms),
        )
        placebo_trades, placebo_parent_audit = replay_lifecycle_train(
            metaorders,
            books_by_coin,
            leader_events,
            required_observed_fills=PARENT_REQUIRED_OBSERVED_FILLS,
            horizon_ms=PARENT_MAX_HOLD_MS,
            train_start_ms=int(train_start_ms),
            train_end_ms=int(train_end_ms),
            direction_multiplier=-1,
        )
    else:
        parent_trades = []
        placebo_trades = []
        parent_audit = {"replay": {"INVALID_OR_MISSING_TRAIN_BOUNDS": len(continuations)}}
        placebo_parent_audit = dict(parent_audit)

    variants: list[dict[str, Any]] = []
    for keep_fraction in KEEP_FRACTIONS:
        efficient, efficiency_audit = select_entry_efficiency(
            parent_trades,
            keep_fraction=keep_fraction,
        )
        for vault_limit in VAULT_DAILY_LIMITS:
            admitted, budget_audit = apply_causal_daily_risk_budget(
                efficient,
                max_entries_per_vault_day=vault_limit,
                max_entries_per_coin_day=COIN_DAILY_LIMIT,
            )
            admitted_ids = _signal_ids(admitted)
            placebo_admitted = [
                dict(row)
                for row in placebo_trades
                if str(row.get("metaorder_id") or "") in admitted_ids
            ]
            annotated = [
                {
                    **row,
                    "mechanism": MECHANISM,
                    "max_entries_per_vault_day": vault_limit,
                    "max_entries_per_coin_day": COIN_DAILY_LIMIT,
                }
                for row in admitted
            ]
            variants.append(
                {
                    "entry_efficiency_keep_fraction": keep_fraction,
                    "entry_efficiency_threshold": efficiency_audit[
                        "learned_entry_efficiency_threshold"
                    ],
                    "max_entries_per_vault_day": vault_limit,
                    "max_entries_per_coin_day": COIN_DAILY_LIMIT,
                    "entry_efficiency_audit": efficiency_audit,
                    "budget_audit": budget_audit,
                    "placebo_signal_match_audit": {
                        "admitted_signal_ids": len(admitted_ids),
                        "matched_placebo_trades": len(placebo_admitted),
                    },
                    **assess_train_variant(
                        annotated,
                        placebo_admitted,
                        trial_count=BONFERRONI_TRIAL_COUNT,
                    ),
                }
            )

    eligible = [row for row in variants if row["eligible"]]
    selected = max(
        eligible,
        key=lambda row: (
            float((row["statistics"] or {}).get("total_lcb_usd") or 0.0),
            float((row["statistics"] or {}).get("net_pnl_usd") or 0.0),
        ),
        default=None,
    )
    diagnostic_best = max(
        variants,
        key=lambda row: float((row["statistics"] or {}).get("net_pnl_usd") or 0.0),
        default=None,
    )
    freeze_candidate = (
        {
            "mechanism": MECHANISM,
            "required_observed_fills": PARENT_REQUIRED_OBSERVED_FILLS,
            "max_hold_ms": PARENT_MAX_HOLD_MS,
            "entry_efficiency_threshold": selected["entry_efficiency_threshold"],
            "max_entries_per_vault_day": selected["max_entries_per_vault_day"],
            "max_entries_per_coin_day": COIN_DAILY_LIMIT,
            "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        }
        if selected
        else None
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "mechanism": MECHANISM,
        "status": "TRAIN_ELIGIBLE_TO_FREEZE" if selected else "NO_ROBUST_TRAIN_CANDIDATE",
        "selection_eligible": selected is not None,
        "physical_freeze_allowed": selected is not None,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_evaluated": False,
        "bounds": bounds,
        "input_audit": dict(input_audit or {}),
        "continuation_audit": continuation_audit,
        "parent_replay_audit": parent_audit,
        "placebo_parent_replay_audit": placebo_parent_audit,
        "fixed_parent": {
            "required_observed_fills": PARENT_REQUIRED_OBSERVED_FILLS,
            "max_hold_ms": PARENT_MAX_HOLD_MS,
        },
        "fixed_grid": {
            "entry_efficiency_keep_fraction": list(KEEP_FRACTIONS),
            "max_entries_per_vault_day": list(VAULT_DAILY_LIMITS),
            "max_entries_per_coin_day": COIN_DAILY_LIMIT,
            "prior_family_trial_count": PRIOR_FAMILY_TRIAL_COUNT,
            "new_trial_count": NEW_TRIAL_COUNT,
            "bonferroni_trial_count": BONFERRONI_TRIAL_COUNT,
        },
        "selected": selected,
        "diagnostic_best_train_variant": diagnostic_best,
        "freeze_candidate": freeze_candidate,
        "freeze_candidate_sha256": stable_hash(freeze_candidate) if freeze_candidate else None,
        "variants": variants,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "MECHANISM",
    "SCHEMA_VERSION",
    "entry_efficiency_score",
    "explore_copy_vault_v8_entry_efficiency_train",
    "select_entry_efficiency",
]
