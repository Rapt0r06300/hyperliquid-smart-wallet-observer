"""Copy-Vault v9 TRAIN-only: causal online leader quality.

The fixed v5 lifecycle is filtered by a v8c entry-efficiency threshold and a
leader score computed only from same-vault shadow trades that fully closed
before each candidate entry.  Daily budgets are then applied chronologically.

PAPER/READ-ONLY.  This module imports no exchange or order client.
"""

from __future__ import annotations

import math
import re
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
from hl_observer.backtesting.train_statistics import (
    exact_net_rank_value,
    select_unambiguous_lcb_candidate,
    stable_hash,
)

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
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$", re.IGNORECASE)


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _exact_positive_timestamp(value: object) -> int | None:
    if type(value) is int and value > 0:
        return value
    return None


def _prior_safe_evidence_refs(
    prior: Sequence[Mapping[str, Any]], *, leader_id: str, as_of_ms: int
) -> tuple[list[dict[str, Any]], str]:
    """Expose only source rows whose SAFE lineage is structurally complete and causal."""
    evidence: list[dict[str, Any]] = []
    complete = bool(prior)
    for trade in prior:
        trade_id = str(trade.get("trade_id") or trade.get("metaorder_id") or "")
        exit_ms = _exact_positive_timestamp(trade.get("exit_ts_ms"))
        fill_refs = trade.get("leader_fill_evidence_refs")
        book_refs = trade.get("execution_book_evidence_refs")
        if (
            trade.get("vault") != leader_id
            or exit_ms is None
            or exit_ms >= as_of_ms
            or trade.get("leader_fill_evidence_status") != "SAFE_CAUSAL_COMPLETE"
            or trade.get("execution_book_safe_evidence_complete") is not True
            or not isinstance(fill_refs, (list, tuple))
            or not fill_refs
            or not isinstance(book_refs, (list, tuple))
            or len(book_refs) != 3
        ):
            complete = False
            continue
        for role, family, refs in (
            ("LEADER_FILL", "copy_vault_fills", fill_refs),
            ("EXECUTION_BOOK", "copy_vault_l2", book_refs),
        ):
            for index, raw in enumerate(refs):
                if not isinstance(raw, Mapping):
                    complete = False
                    continue
                dataset_id = raw.get("dataset_id")
                shard_sha = raw.get("shard_sha256")
                catalog_sha = raw.get("source_catalog_sha256")
                observed_ms = _exact_positive_timestamp(
                    raw.get("event_ts_ms", raw.get("exchange_ts_ms"))
                )
                received_ms = _exact_positive_timestamp(raw.get("received_at_ms"))
                if (
                    not isinstance(dataset_id, str) or not dataset_id.strip()
                    or not isinstance(shard_sha, str)
                    or _SHA256_RE.fullmatch(shard_sha) is None
                    or not isinstance(catalog_sha, str)
                    or _SHA256_RE.fullmatch(catalog_sha) is None
                    or raw.get("quality") != "SAFE"
                    or raw.get("manifest_verified") is not True
                    or raw.get("replay_compatible") is not True
                    or observed_ms is None
                    or received_ms is None
                    or observed_ms > received_ms
                    or received_ms > exit_ms
                    or received_ms > as_of_ms
                ):
                    complete = False
                    continue
                event_id = str(raw.get("event_id") or raw.get("raw_frame_sha256") or index)
                reference = f"v9:{trade_id}:{role}:{dataset_id}:{event_id}"
                evidence.append(
                    {
                        "ref": reference,
                        "leader_id": leader_id,
                        "source": family,
                        "source_family": family,
                        "source_dataset_id": dataset_id.strip(),
                        "source_sha256": shard_sha.lower(),
                        "source_catalog_sha256": catalog_sha.lower(),
                        "quality": "SAFE",
                        "manifest_verified": True,
                        "replay_compatible": True,
                        "observed_at_ms": observed_ms,
                        "received_at_ms": received_ms,
                        "period_start_ms": observed_ms,
                        "period_end_ms": observed_ms,
                        "trade_id": trade_id,
                        "evidence_role": role,
                    }
                )
    unique = {row["ref"]: row for row in evidence}
    if len(unique) != len(evidence):
        complete = False
    status = "SAFE_CAUSAL_COMPLETE" if complete and unique else "INCOMPLETE_OR_UNVERIFIED"
    return [unique[key] for key in sorted(unique)], status


def apply_causal_online_leader_quality(
    candidates: Sequence[Mapping[str, Any]],
    shadow_trades: Sequence[Mapping[str, Any]],
    *,
    minimum_prior_closed: int,
    history_window: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Admit candidates using only same-vault outcomes already closed at entry."""

    if type(minimum_prior_closed) is not int or minimum_prior_closed <= 0:
        raise ValueError("minimum_prior_closed must be positive")
    if type(history_window) is not int or history_window < minimum_prior_closed:
        raise ValueError("history_window must cover minimum_prior_closed")

    history_by_vault: dict[str, list[dict[str, Any]]] = {}
    invalid_history = 0
    for raw in shadow_trades:
        row = dict(raw)
        vault = str(row.get("vault") or "")
        net = _finite(row.get("net_pnl_usd"))
        exit_ms = _exact_positive_timestamp(row.get("exit_ts_ms"))
        if not vault or net is None or exit_ms is None:
            invalid_history += 1
            continue
        history_by_vault.setdefault(vault, []).append(
            {**row, "exit_ts_ms": exit_ms, "net_pnl_usd": net}
        )
    for rows in history_by_vault.values():
        rows.sort(key=lambda row: (int(row["exit_ts_ms"]), str(row.get("trade_id") or "")))

    audit: dict[str, Any] = {
        "CANDIDATE_ROWS": len(candidates),
        "INVALID_HISTORY_ROWS": invalid_history,
        "leader_decisions": [],
    }
    selected: list[dict[str, Any]] = []
    ordered = sorted(
        enumerate(dict(row) for row in candidates),
        key=lambda item: (
            _exact_positive_timestamp(item[1].get("entry_ts_ms")) or 0,
            str(item[1].get("trade_id") or item[1].get("metaorder_id") or item[0]),
        ),
    )
    for original_index, row in ordered:
        vault = str(row.get("vault") or "")
        entry_ms = _exact_positive_timestamp(row.get("entry_ts_ms"))
        candidate_id = str(
            row.get("trade_id") or row.get("metaorder_id") or f"candidate-{original_index}"
        )
        if not vault or entry_ms is None:
            audit["INVALID_CANDIDATE_REJECTED"] = (
                audit.get("INVALID_CANDIDATE_REJECTED", 0) + 1
            )
            audit["leader_decisions"].append(
                {
                    "decision_scope": "CANDIDATE_SIGNAL_AT_ENTRY",
                    "candidate_trade_id": candidate_id,
                    "leader_id": vault or None,
                    "as_of_ms": entry_ms,
                    "outcome": "REJECTED",
                    "reason": (
                        "INVALID_CANDIDATE_TIMESTAMP" if entry_ms is None
                        else "LEADER_ID_MISSING"
                    ),
                    "prior_count": 0,
                    "prior_trade_ids": [],
                    "evidence_refs": [],
                    "evidence_status": "INCOMPLETE_OR_UNVERIFIED",
                }
            )
            continue
        prior = [
            past
            for past in history_by_vault.get(vault, [])
            if past["exit_ts_ms"] < entry_ms
        ][-history_window:]
        prior_trade_ids = [
            str(past.get("trade_id") or past.get("metaorder_id") or "") for past in prior
        ]
        prior_latest_exit = max(
            (int(past["exit_ts_ms"]) for past in prior), default=None
        )
        if len(prior) < int(minimum_prior_closed):
            audit["INSUFFICIENT_PRIOR_HISTORY_REJECTED"] = (
                audit.get("INSUFFICIENT_PRIOR_HISTORY_REJECTED", 0) + 1
            )
            refs, evidence_status = _prior_safe_evidence_refs(
                prior, leader_id=vault, as_of_ms=entry_ms
            )
            audit["leader_decisions"].append(
                {
                    "decision_scope": "CANDIDATE_SIGNAL_AT_ENTRY",
                    "candidate_trade_id": candidate_id,
                    "leader_id": vault,
                    "as_of_ms": entry_ms,
                    "outcome": "REJECTED",
                    "reason": "INSUFFICIENT_PRIOR_CLOSED_HISTORY",
                    "prior_count": len(prior),
                    "prior_trade_ids": prior_trade_ids,
                    "prior_latest_exit_ts_ms": prior_latest_exit,
                    "prior_mean_net_pnl_usd": None,
                    "evidence_refs": refs,
                    "evidence_status": evidence_status,
                }
            )
            continue
        prior_mean = sum(float(past["net_pnl_usd"]) for past in prior) / len(prior)
        refs, evidence_status = _prior_safe_evidence_refs(
            prior, leader_id=vault, as_of_ms=entry_ms
        )
        if prior_mean <= 0.0:
            audit["NON_POSITIVE_PRIOR_MEAN_REJECTED"] = (
                audit.get("NON_POSITIVE_PRIOR_MEAN_REJECTED", 0) + 1
            )
            audit["leader_decisions"].append(
                {
                    "decision_scope": "CANDIDATE_SIGNAL_AT_ENTRY",
                    "candidate_trade_id": candidate_id,
                    "leader_id": vault,
                    "as_of_ms": entry_ms,
                    "outcome": "DEMOTED",
                    "reason": "NON_POSITIVE_PRIOR_NET_MEAN",
                    "prior_count": len(prior),
                    "prior_trade_ids": prior_trade_ids,
                    "prior_latest_exit_ts_ms": prior_latest_exit,
                    "prior_mean_net_pnl_usd": prior_mean,
                    "evidence_refs": refs,
                    "evidence_status": evidence_status,
                }
            )
            continue
        audit["leader_decisions"].append(
            {
                "decision_scope": "CANDIDATE_SIGNAL_AT_ENTRY",
                "candidate_trade_id": candidate_id,
                "leader_id": vault,
                "as_of_ms": entry_ms,
                "outcome": "RETAINED",
                "reason": "POSITIVE_PRIOR_NET_MEAN",
                "prior_count": len(prior),
                "prior_trade_ids": prior_trade_ids,
                "prior_latest_exit_ts_ms": prior_latest_exit,
                "prior_mean_net_pnl_usd": prior_mean,
                "evidence_refs": refs,
                "evidence_status": evidence_status,
            }
        )
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
    leader_decision_traces: list[dict[str, Any]] = []
    for minimum_prior in MINIMUM_PRIOR_CLOSED:
        for history_window in HISTORY_WINDOWS:
            quality_rows, quality_audit = apply_causal_online_leader_quality(
                efficient,
                parent_trades,
                minimum_prior_closed=minimum_prior,
                history_window=history_window,
            )
            decisions = list(quality_audit.get("leader_decisions") or [])
            leader_decision_traces.append(
                {
                    "minimum_prior_closed": minimum_prior,
                    "history_window": history_window,
                    "candidate_decision_count": len(decisions),
                    "safe_causal_complete_count": sum(
                        row.get("evidence_status") == "SAFE_CAUSAL_COMPLETE"
                        for row in decisions
                    ),
                    "decisions": decisions,
                }
            )
            quality_audit_summary = {
                key: value for key, value in quality_audit.items()
                if key != "leader_decisions"
            }
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
                        "leader_quality_audit": quality_audit_summary,
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
    selected, selection_resolution = select_unambiguous_lcb_candidate(eligible)
    diagnostic_best = max(
        variants,
        key=lambda row: exact_net_rank_value(row["statistics"] or {}),
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
        "selection_numeric_resolution": selection_resolution,
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
        "leader_decision_traces": {
            "schema_version": "copy_vault.leader_quality_decision_trace.v1",
            "scope": "TRAIN_ONLY_PRE_FREEZE",
            "decision_scope": "V9_ONLINE_LEADER_QUALITY_AFTER_ENTRY_EFFICIENCY",
            "durability": "CAMPAIGN_RESULT_ONLY_NOT_APPEND_ONLY_REVIEW_LEDGER",
            "source_bytes_rehashed_here": False,
            "canonical_safe_audit_required": True,
            "traces": leader_decision_traces,
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
