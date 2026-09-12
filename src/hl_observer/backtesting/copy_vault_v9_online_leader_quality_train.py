"""Copy-Vault v9 TRAIN-only: causal online leader quality.

The fixed v5 lifecycle is filtered by a v8c entry-efficiency threshold and a
leader score computed only from same-vault shadow trades that fully closed
before each candidate entry.  Daily budgets are then applied chronologically.

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
from hl_observer.backtesting.copy_vault_v8_entry_efficiency_train import (
    select_entry_efficiency,
)
from hl_observer.backtesting.train_statistics import stable_hash

SCHEMA_VERSION = "hypersmart.copy_vault_v9_online_leader_quality_train.v1"
MECHANISM = "copy_vault_v9_causal_online_leader_quality"
PARENT_REQUIRED_OBSERVED_FILLS = 2
PARENT_MAX_HOLD_MS = 3_600_000
ENTRY_EFFICIENCY_KEEP_FRACTION = 0.65
MINIMUM_PRIOR_CLOSED = (1, 2)
HISTORY_WINDOWS = (4, 8)
VAULT_DAILY_LIMITS = (1, 2)
COIN_DAILY_LIMIT = 1
PRIOR_FAMILY_TRIAL_COUNT = 104
NEW_TRIAL_COUNT = (
    len(MINIMUM_PRIOR_CLOSED) * len(HISTORY_WINDOWS) * len(VAULT_DAILY_LIMITS)
)
BONFERRONI_TRIAL_COUNT = PRIOR_FAMILY_TRIAL_COUNT + NEW_TRIAL_COUNT


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def apply_causal_online_leader_quality(
    candidates: Sequence[Mapping[str, Any]],
    shadow_trades: Sequence[Mapping[str, Any]],
    *,
    minimum_prior_closed: int,
    history_window: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Admit candidates using only same-vault outcomes already closed at entry."""

    if int(minimum_prior_closed) <= 0:
        raise ValueError("minimum_prior_closed must be positive")
    if int(history_window) < int(minimum_prior_closed):
        raise ValueError("history_window must cover minimum_prior_closed")

    history_by_vault: dict[str, list[dict[str, Any]]] = {}
    invalid_history = 0
    for raw in shadow_trades:
        row = dict(raw)
        vault = str(row.get("vault") or "")
        net = _finite(row.get("net_pnl_usd"))
        try:
            exit_ms = int(row.get("exit_ts_ms") or 0)
        except (TypeError, ValueError, OverflowError):
            exit_ms = 0
        if not vault or net is None or exit_ms <= 0:
            invalid_history += 1
            continue
        history_by_vault.setdefault(vault, []).append(
            {**row, "exit_ts_ms": exit_ms, "net_pnl_usd": net}
        )
    for rows in history_by_vault.values():
        rows.sort(key=lambda row: (int(row["exit_ts_ms"]), str(row.get("trade_id") or "")))

    audit: dict[str, int] = {
        "CANDIDATE_ROWS": len(candidates),
        "INVALID_HISTORY_ROWS": invalid_history,
    }
    selected: list[dict[str, Any]] = []
    ordered = sorted(
        (dict(row) for row in candidates),
        key=lambda row: (int(row.get("entry_ts_ms") or 0), str(row.get("trade_id") or "")),
    )
    for row in ordered:
        vault = str(row.get("vault") or "")
        try:
            entry_ms = int(row.get("entry_ts_ms") or 0)
        except (TypeError, ValueError, OverflowError):
            entry_ms = 0
        if not vault or entry_ms <= 0:
            audit["INVALID_CANDIDATE_REJECTED"] = (
                audit.get("INVALID_CANDIDATE_REJECTED", 0) + 1
            )
            continue
        prior = [
            past
            for past in history_by_vault.get(vault, [])
            if int(past["exit_ts_ms"]) < entry_ms
        ][-int(history_window) :]
        if len(prior) < int(minimum_prior_closed):
            audit["INSUFFICIENT_PRIOR_HISTORY_REJECTED"] = (
                audit.get("INSUFFICIENT_PRIOR_HISTORY_REJECTED", 0) + 1
            )
            continue
        prior_mean = sum(float(past["net_pnl_usd"]) for past in prior) / len(prior)
        if prior_mean <= 0.0:
            audit["NON_POSITIVE_PRIOR_MEAN_REJECTED"] = (
                audit.get("NON_POSITIVE_PRIOR_MEAN_REJECTED", 0) + 1
            )
            continue
        selected.append(
            {
                **row,
                "leader_quality_prior_count": len(prior),
                "leader_quality_prior_mean_net_pnl_usd": prior_mean,
                "leader_quality_history_window": int(history_window),
                "leader_quality_minimum_prior_closed": int(minimum_prior_closed),
                "leader_quality_latest_exit_ts_ms": max(
                    int(past["exit_ts_ms"]) for past in prior
                ),
                "leader_quality_uses_current_or_future_outcome": False,
            }
        )
    audit["ADMITTED"] = len(selected)
    return selected, audit


def _signal_ids(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    return {str(row.get("metaorder_id") or "") for row in rows if row.get("metaorder_id")}


def explore_copy_vault_v9_online_leader_quality_train(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, Sequence[Mapping[str, Any]]],
    leader_events: Sequence[Mapping[str, Any]],
    *,
    input_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate the eight predeclared online-quality variants on TRAIN only."""

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

    efficient, efficiency_audit = select_entry_efficiency(
        parent_trades,
        keep_fraction=ENTRY_EFFICIENCY_KEEP_FRACTION,
    )
    variants: list[dict[str, Any]] = []
    for minimum_prior in MINIMUM_PRIOR_CLOSED:
        for history_window in HISTORY_WINDOWS:
            quality_rows, quality_audit = apply_causal_online_leader_quality(
                efficient,
                parent_trades,
                minimum_prior_closed=minimum_prior,
                history_window=history_window,
            )
            for vault_limit in VAULT_DAILY_LIMITS:
                admitted, budget_audit = apply_causal_daily_risk_budget(
                    quality_rows,
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
                        "minimum_prior_closed": minimum_prior,
                        "history_window": history_window,
                        "max_entries_per_vault_day": vault_limit,
                        "max_entries_per_coin_day": COIN_DAILY_LIMIT,
                        "entry_efficiency_audit": efficiency_audit,
                        "leader_quality_audit": quality_audit,
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
            "entry_efficiency_threshold": efficiency_audit.get(
                "learned_entry_efficiency_threshold"
            ),
            "minimum_prior_closed": selected["minimum_prior_closed"],
            "history_window": selected["history_window"],
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
            "entry_efficiency_keep_fraction": ENTRY_EFFICIENCY_KEEP_FRACTION,
        },
        "fixed_grid": {
            "minimum_prior_closed": list(MINIMUM_PRIOR_CLOSED),
            "history_window": list(HISTORY_WINDOWS),
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
    "apply_causal_online_leader_quality",
    "explore_copy_vault_v9_online_leader_quality_train",
]
