"""Copy-Vault v7 TRAIN-only: causal leader-exit flow continuation.

Unlike lifecycle copying, this mechanism treats a leader REDUCE or CLOSE as
the signal itself.  A reduction of a long position is sell flow and a
reduction of a short position is buy flow.  Same-market slices are collapsed
before replay, then every entry and exit is settled against observed causal L2.

PAPER/READ-ONLY.  No exchange or order client is imported here.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.copy_vault_executable import execute_metaorder, temporal_bounds
from hl_observer.backtesting.copy_vault_protocol import MAX_OPEN_POSITIONS, MAX_TARGET_LAG_MS
from hl_observer.backtesting.copy_vault_v4_train import assess_train_variant
from hl_observer.backtesting.train_statistics import stable_hash

SCHEMA_VERSION = "hypersmart.copy_vault_v7_exit_flow_train.v1"
MECHANISM = "copy_vault_v7_causal_leader_exit_flow"
EXIT_ACTIONS = frozenset({"REDUCE", "CLOSE"})
SLICE_GAP_MS = 5_000
COPY_DELAYS_MS = (250, 1_000)
HORIZONS_MS = (30_000, 300_000, 900_000, 3_600_000)
PRIOR_FAMILY_TRIAL_COUNT = 76
NEW_TRIAL_COUNT = len(COPY_DELAYS_MS) * len(HORIZONS_MS)
BONFERRONI_TRIAL_COUNT = PRIOR_FAMILY_TRIAL_COUNT + NEW_TRIAL_COUNT


def _causal_exit(row: Mapping[str, Any]) -> dict[str, Any] | None:
    try:
        event_ms = int(row.get("ts_ms") or 0)
        observed_ms = int(row.get("observed_at_ms") or 0)
        leader_direction = int(row.get("direction") or 0)
    except (TypeError, ValueError, OverflowError):
        return None
    action = str(row.get("action") or "").upper()
    vault = str(row.get("vault") or "").strip()
    coin = str(row.get("coin") or "").upper().strip()
    if not (
        action in EXIT_ACTIONS
        and str(row.get("source") or "") == "LIVE_WS"
        and row.get("is_snapshot") is False
        and observed_ms >= event_ms > 0
        and leader_direction in (-1, 1)
        and vault
        and coin
    ):
        return None
    return {
        **dict(row),
        "action": action,
        "vault": vault,
        "coin": coin,
        "ts_ms": event_ms,
        "observed_at_ms": observed_ms,
        "direction": leader_direction,
        "event_id": str(
            row.get("event_id")
            or row.get("fill_id")
            or row.get("hash")
            or f"{vault}:{coin}:{event_ms}:{action}"
        ),
    }


def cluster_causal_exit_flow(
    events: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Collapse rapid exit slices without using prices after the signal."""

    valid: list[dict[str, Any]] = []
    rejected = 0
    for raw in events:
        row = _causal_exit(raw)
        if row is None:
            rejected += 1
        else:
            valid.append(row)
    valid.sort(
        key=lambda row: (
            int(row["observed_at_ms"]),
            str(row["vault"]),
            str(row["coin"]),
            str(row["event_id"]),
        )
    )
    groups: list[list[dict[str, Any]]] = []
    last_group_by_key: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for row in valid:
        key = (row["vault"], row["coin"], int(row["direction"]))
        current = last_group_by_key.get(key)
        if current:
            previous = current[-1]
            gap = int(row["observed_at_ms"]) - int(previous["observed_at_ms"])
        else:
            gap = SLICE_GAP_MS + 1
        if current is not None and 0 <= gap <= SLICE_GAP_MS:
            current.append(row)
        else:
            current = [row]
            groups.append(current)
            last_group_by_key[key] = current

    groups.sort(key=lambda members: int(members[0]["observed_at_ms"]))

    signals: list[dict[str, Any]] = []
    for members in groups:
        first = members[0]
        material = "|".join(
            (
                MECHANISM,
                str(first["vault"]),
                str(first["coin"]),
                str(first["direction"]),
                str(first["observed_at_ms"]),
                str(first["event_id"]),
            )
        )
        signals.append(
            {
                "metaorder_id": hashlib.sha256(material.encode("utf-8")).hexdigest(),
                "vault": first["vault"],
                "coin": first["coin"],
                "direction": -int(first["direction"]),
                "leader_position_direction": int(first["direction"]),
                "signal_ts_ms": int(first["observed_at_ms"]),
                "first_fill_ts_ms": int(first["ts_ms"]),
                "signal_source": "LIVE_WS",
                "causal_forward_eligible": True,
                "exit_action": first["action"],
                "member_event_ids": [str(row["event_id"]) for row in members],
            }
        )
    return signals, {
        "input_events": len(events),
        "causal_exit_events": len(valid),
        "noncausal_or_nonexit_events_rejected": rejected,
        "exit_flow_signals": len(signals),
        "collapsed_slices": len(valid) - len(signals),
    }


def replay_exit_flow_train(
    events: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    copy_delay_ms: int,
    horizon_ms: int,
    train_start_ms: int | None,
    train_end_ms: int | None,
    direction_multiplier: int = 1,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Replay one fixed exit-flow variant on supplied TRAIN bounds."""

    signals, signal_audit = cluster_causal_exit_flow(events)
    if (
        train_start_ms is None
        or train_end_ms is None
        or int(train_end_ms) < int(train_start_ms)
    ):
        return [], {
            "signals": signal_audit,
            "replay": {
                "completed_positions": 0,
                "INVALID_OR_MISSING_TRAIN_BOUNDS": len(signals),
            },
        }
    continuous = {
        str(coin).upper(): sorted(
            [
                dict(row)
                for row in rows
                if row.get("causal_observation") is True and not row.get("checkpoint_id")
            ],
            key=lambda row: int(row.get("ts_ms") or 0),
        )
        for coin, rows in books_by_coin.items()
    }
    counters: Counter[str] = Counter({"signals_considered": 0, "completed_positions": 0})
    active_exit_times: list[int] = []
    trades: list[dict[str, Any]] = []
    seen: set[str] = set()
    for signal in signals:
        signal_ms = int(signal["signal_ts_ms"])
        if signal_ms < int(train_start_ms) or signal_ms > int(train_end_ms):
            continue
        counters["signals_considered"] += 1
        trade, reason = execute_metaorder(
            signal,
            continuous.get(str(signal["coin"]).upper(), []),
            horizon_ms=int(horizon_ms),
            direction_multiplier=int(direction_multiplier),
            copy_delay_ms=int(copy_delay_ms),
            require_causal_books=True,
        )
        if trade is None:
            counters[reason] += 1
            continue
        active_exit_times = [
            ts for ts in active_exit_times if ts > int(trade["entry_ts_ms"])
        ]
        if len(active_exit_times) >= MAX_OPEN_POSITIONS:
            counters["portfolio_capacity_rejected"] += 1
            continue
        trade_id = str(trade["trade_id"])
        if trade_id in seen:
            counters["DUPLICATE_TRADE_ID_REJECTED"] += 1
            continue
        seen.add(trade_id)
        active_exit_times.append(int(trade["exit_ts_ms"]))
        trades.append(
            {
                **trade,
                "mechanism": MECHANISM,
                "walk_forward_segment": "train",
                "leader_position_direction": signal["leader_position_direction"],
                "leader_exit_action": signal["exit_action"],
                "leader_exit_event_ids": list(signal["member_event_ids"]),
                "copy_delay_ms": int(copy_delay_ms),
                "markout_horizon_ms": int(horizon_ms),
                "paper_read_only": True,
                "real_execution": False,
            }
        )
        counters["completed_positions"] += 1
    return trades, {"signals": signal_audit, "replay": dict(counters)}


def explore_copy_vault_v7_exit_flow_train(
    leader_events: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    input_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate the predeclared 2 x 4 exit-flow grid on TRAIN only."""

    signals, signal_audit = cluster_causal_exit_flow(leader_events)
    variants: list[dict[str, Any]] = []
    for delay_ms in COPY_DELAYS_MS:
        for horizon_ms in HORIZONS_MS:
            bounds = temporal_bounds(
                signals,
                purge_ms=int(delay_ms) + int(horizon_ms) + MAX_TARGET_LAG_MS,
            )
            trades, replay_audit = replay_exit_flow_train(
                leader_events,
                books_by_coin,
                copy_delay_ms=delay_ms,
                horizon_ms=horizon_ms,
                train_start_ms=bounds.get("train_start_ms"),
                train_end_ms=bounds.get("train_end_ms"),
            )
            placebo, placebo_audit = replay_exit_flow_train(
                leader_events,
                books_by_coin,
                copy_delay_ms=delay_ms,
                horizon_ms=horizon_ms,
                train_start_ms=bounds.get("train_start_ms"),
                train_end_ms=bounds.get("train_end_ms"),
                direction_multiplier=-1,
            )
            variants.append(
                {
                    "copy_delay_ms": delay_ms,
                    "markout_horizon_ms": horizon_ms,
                    "bounds": bounds,
                    "replay_audit": replay_audit,
                    "placebo_replay_audit": placebo_audit,
                    **assess_train_variant(
                        trades,
                        placebo,
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
            "slice_gap_ms": SLICE_GAP_MS,
            "copy_delay_ms": selected["copy_delay_ms"],
            "markout_horizon_ms": selected["markout_horizon_ms"],
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
        "signal_audit": signal_audit,
        "input_audit": dict(input_audit or {}),
        "fixed_grid": {
            "copy_delay_ms": list(COPY_DELAYS_MS),
            "markout_horizon_ms": list(HORIZONS_MS),
            "slice_gap_ms": SLICE_GAP_MS,
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
    "cluster_causal_exit_flow",
    "explore_copy_vault_v7_exit_flow_train",
    "replay_exit_flow_train",
]
