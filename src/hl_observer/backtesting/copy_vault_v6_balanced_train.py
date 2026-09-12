"""Copy-Vault v6 TRAIN-only: causal daily portfolio risk budgets.

The v5 lifecycle challenger can be economically positive while almost every
trade comes from one high-frequency vault.  This module keeps the v5 signal,
cost, entry and exit contracts fixed, then applies a causal admission budget
using only the UTC day, vault, coin and earlier admitted entries.  Outcomes
never participate in admission.

PAPER/READ-ONLY.  No exchange or order client is imported here.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.copy_vault_executable import (
    select_observed_continuations,
    temporal_bounds,
)
from hl_observer.backtesting.copy_vault_protocol import COPY_DELAY_MS, MAX_TARGET_LAG_MS
from hl_observer.backtesting.copy_vault_v4_train import assess_train_variant
from hl_observer.backtesting.copy_vault_v5_lifecycle_train import replay_lifecycle_train
from hl_observer.backtesting.train_statistics import stable_hash

SCHEMA_VERSION = "hypersmart.copy_vault_v6_balanced_train.v1"
MECHANISM = "copy_vault_v6_causal_daily_risk_budget"
PARENT_REQUIRED_OBSERVED_FILLS = 2
PARENT_MAX_HOLD_MS = 3_600_000
PARENT_TRIAL_COUNT = 16
VAULT_DAILY_LIMITS = (1, 2)
COIN_DAILY_LIMITS = (1, 2)
NEW_TRIAL_COUNT = len(VAULT_DAILY_LIMITS) * len(COIN_DAILY_LIMITS)
BONFERRONI_TRIAL_COUNT = PARENT_TRIAL_COUNT + NEW_TRIAL_COUNT
UTC_DAY_MS = 86_400_000


def apply_causal_daily_risk_budget(
    trades: Sequence[Mapping[str, Any]],
    *,
    max_entries_per_vault_day: int,
    max_entries_per_coin_day: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Admit trades using identifiers and prior counters only."""

    if int(max_entries_per_vault_day) <= 0 or int(max_entries_per_coin_day) <= 0:
        raise ValueError("daily entry limits must be positive")
    vault_counts: Counter[tuple[int, str]] = Counter()
    coin_counts: Counter[tuple[int, str]] = Counter()
    selected: list[dict[str, Any]] = []
    audit: Counter[str] = Counter(
        {
            "ADMITTED": 0,
            "VAULT_DAILY_BUDGET_REJECTED": 0,
            "COIN_DAILY_BUDGET_REJECTED": 0,
        }
    )
    for raw in sorted(
        (dict(row) for row in trades),
        key=lambda row: (
            int(row.get("entry_ts_ms") or 0),
            str(row.get("trade_id") or ""),
        ),
    ):
        day = int(raw.get("entry_ts_ms") or 0) // UTC_DAY_MS
        vault_key = (day, str(raw.get("vault") or "UNKNOWN"))
        coin_key = (day, str(raw.get("coin") or "UNKNOWN").upper())
        if vault_counts[vault_key] >= int(max_entries_per_vault_day):
            audit["VAULT_DAILY_BUDGET_REJECTED"] += 1
            continue
        if coin_counts[coin_key] >= int(max_entries_per_coin_day):
            audit["COIN_DAILY_BUDGET_REJECTED"] += 1
            continue
        vault_counts[vault_key] += 1
        coin_counts[coin_key] += 1
        selected.append(
            {
                **raw,
                "mechanism": MECHANISM,
                "max_entries_per_vault_day": int(max_entries_per_vault_day),
                "max_entries_per_coin_day": int(max_entries_per_coin_day),
                "admission_uses_outcome": False,
            }
        )
        audit["ADMITTED"] += 1
    audit["INPUT_TRADES"] = len(trades)
    return selected, dict(audit)


def explore_copy_vault_v6_balanced_train(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, Sequence[Mapping[str, Any]]],
    leader_events: Sequence[Mapping[str, Any]],
    *,
    input_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate the four predeclared admission budgets on TRAIN only."""

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
    for vault_limit in VAULT_DAILY_LIMITS:
        for coin_limit in COIN_DAILY_LIMITS:
            selected, admission_audit = apply_causal_daily_risk_budget(
                parent_trades,
                max_entries_per_vault_day=vault_limit,
                max_entries_per_coin_day=coin_limit,
            )
            placebo_selected, placebo_admission_audit = apply_causal_daily_risk_budget(
                placebo_trades,
                max_entries_per_vault_day=vault_limit,
                max_entries_per_coin_day=coin_limit,
            )
            variants.append(
                {
                    "max_entries_per_vault_day": vault_limit,
                    "max_entries_per_coin_day": coin_limit,
                    "admission_audit": admission_audit,
                    "placebo_admission_audit": placebo_admission_audit,
                    **assess_train_variant(
                        selected,
                        placebo_selected,
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
            "max_entries_per_vault_day": selected["max_entries_per_vault_day"],
            "max_entries_per_coin_day": selected["max_entries_per_coin_day"],
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
            "trial_count": PARENT_TRIAL_COUNT,
        },
        "fixed_grid": {
            "max_entries_per_vault_day": list(VAULT_DAILY_LIMITS),
            "max_entries_per_coin_day": list(COIN_DAILY_LIMITS),
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
    "apply_causal_daily_risk_budget",
    "explore_copy_vault_v6_balanced_train",
]
