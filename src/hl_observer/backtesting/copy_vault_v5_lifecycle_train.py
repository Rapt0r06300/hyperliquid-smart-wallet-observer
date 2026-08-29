"""Copy-Vault V5 TRAIN-only: sortie causale sur réduction du leader.

La collecte live commence souvent au milieu d'une position leader. Les données
actuelles contiennent donc beaucoup de ``ADD`` et de ``REDUCE``, mais presque
aucun cycle causal ``OPEN -> CLOSE`` complet. Cette hypothèse attend toujours
N fills d'entrée observés, ouvre après le délai paper pré-déclaré, puis ferme
entièrement la tranche suiveuse au premier ``REDUCE``/``CLOSE`` causal du même
leader et du même marché. Le time-stop canonique reste le repli obligatoire.

La grille est finie et TRAIN-only. Les prix, frais, spread, latence et capacité
passent par le replay exécutable canonique. Aucun heldout n'est lu et ce module
ne peut jamais envoyer d'ordre.
"""
from __future__ import annotations

import bisect
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.copy_vault_executable import (
    execute_metaorder,
    select_observed_continuations,
    temporal_bounds,
)
from hl_observer.backtesting.copy_vault_protocol import (
    COPY_DELAY_MS,
    HORIZONS_MS,
    MAX_OPEN_POSITIONS,
    MAX_TARGET_LAG_MS,
    NOTIONAL_USD,
)
from hl_observer.backtesting.copy_vault_v4_train import assess_train_variant
from hl_observer.backtesting.train_statistics import stable_hash

SCHEMA_VERSION = "hypersmart.copy_vault_v5_lifecycle_train.v1"
MECHANISM = "copy_vault_v5_causal_leader_reduce_or_time_stop"
REQUIRED_OBSERVED_FILLS = (2, 3, 4, 5)
LEADER_EXIT_ACTIONS = frozenset({"REDUCE", "CLOSE"})
EXIT_POLICY = "FULL_FOLLOWER_EXIT_ON_FIRST_CAUSAL_LEADER_REDUCE_OR_CLOSE"


def _is_causal_leader_exit(row: Mapping[str, Any]) -> bool:
    try:
        event_ms = int(row.get("ts_ms") or 0)
        observed_ms = int(row.get("observed_at_ms") or 0)
        direction = int(row.get("direction") or 0)
    except (TypeError, ValueError, OverflowError):
        return False
    return bool(
        str(row.get("action") or "").upper() in LEADER_EXIT_ACTIONS
        and str(row.get("source") or "") == "LIVE_WS"
        and row.get("is_snapshot") is False
        and observed_ms >= event_ms > 0
        and direction in (-1, 1)
        and row.get("vault")
        and row.get("coin")
    )


def index_causal_leader_exits(
    events: Sequence[Mapping[str, Any]],
) -> tuple[dict[tuple[str, str, int], list[dict[str, Any]]], dict[str, Any]]:
    """Indexe uniquement les sorties qui existaient réellement au temps local."""

    indexed: dict[tuple[str, str, int], list[dict[str, Any]]] = defaultdict(list)
    actions: Counter[str] = Counter()
    rejected = 0
    for raw in events:
        if not _is_causal_leader_exit(raw):
            rejected += 1
            continue
        row = dict(raw)
        row["action"] = str(row["action"]).upper()
        row["coin"] = str(row["coin"]).upper()
        row["vault"] = str(row["vault"])
        row["direction"] = int(row["direction"])
        row["observed_at_ms"] = int(row["observed_at_ms"])
        indexed[(row["vault"], row["coin"], row["direction"])].append(row)
        actions[row["action"]] += 1
    for rows in indexed.values():
        rows.sort(
            key=lambda row: (
                int(row["observed_at_ms"]),
                str(row.get("event_id") or row.get("fill_id") or ""),
            )
        )
    return dict(indexed), {
        "input_events": len(events),
        "causal_exit_events": sum(len(rows) for rows in indexed.values()),
        "noncausal_or_nonexit_events_rejected": rejected,
        "exit_actions": dict(sorted(actions.items())),
        "indexed_leader_market_directions": len(indexed),
        "causal_policy": (
            "LIVE_WS_non_snapshot_with_monotonic_exchange_and_receive_times"
        ),
    }


def _continuous_causal_books(
    books_by_coin: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    selected: dict[str, list[dict[str, Any]]] = {}
    for raw_coin, raw_rows in books_by_coin.items():
        rows = [
            dict(row)
            for row in raw_rows
            if row.get("causal_observation") is True
            and not row.get("checkpoint_id")
        ]
        rows.sort(key=lambda row: int(row.get("ts_ms") or 0))
        if rows:
            selected[str(raw_coin).upper()] = rows
    return selected


def _first_book_at_or_after(
    rows: Sequence[Mapping[str, Any]], target_ms: int
) -> Mapping[str, Any] | None:
    timestamps = [int(row.get("ts_ms") or 0) for row in rows]
    index = bisect.bisect_left(timestamps, int(target_ms))
    if index >= len(rows):
        return None
    lag_ms = timestamps[index] - int(target_ms)
    return rows[index] if 0 <= lag_ms <= MAX_TARGET_LAG_MS else None


def _first_exit_after(
    rows: Sequence[Mapping[str, Any]], entry_ts_ms: int
) -> Mapping[str, Any] | None:
    observed = [int(row.get("observed_at_ms") or 0) for row in rows]
    index = bisect.bisect_right(observed, int(entry_ts_ms))
    return rows[index] if index < len(rows) else None


def _replay_selected(
    continuations: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, Sequence[Mapping[str, Any]]],
    exit_index: Mapping[tuple[str, str, int], Sequence[Mapping[str, Any]]],
    *,
    required_observed_fills: int,
    horizon_ms: int,
    train_start_ms: int,
    train_end_ms: int,
    direction_multiplier: int,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    continuous_books = _continuous_causal_books(books_by_coin)
    counters: dict[str, int] = {
        "metaorders_considered": 0,
        "completed_positions": 0,
        "portfolio_capacity_rejected": 0,
    }
    active_exit_times: list[int] = []
    seen: set[str] = set()
    trades: list[dict[str, Any]] = []
    for metaorder in sorted(
        continuations,
        key=lambda row: (int(row.get("signal_ts_ms") or 0), str(row.get("metaorder_id") or "")),
    ):
        signal_ms = int(metaorder.get("signal_ts_ms") or 0)
        if signal_ms < int(train_start_ms) or signal_ms > int(train_end_ms):
            continue
        counters["metaorders_considered"] += 1
        coin = str(metaorder.get("coin") or "").upper()
        books = continuous_books.get(coin, [])
        entry = _first_book_at_or_after(books, signal_ms + COPY_DELAY_MS)
        if entry is None:
            counters["STALE_OR_MISSING_ENTRY_BOOK"] = (
                counters.get("STALE_OR_MISSING_ENTRY_BOOK", 0) + 1
            )
            continue
        key = (
            str(metaorder.get("vault") or ""),
            coin,
            int(metaorder.get("direction") or 0),
        )
        leader_exit = _first_exit_after(
            exit_index.get(key, []), int(entry["ts_ms"])
        )
        time_stop_ms = int(entry["ts_ms"]) + int(horizon_ms)
        leader_exit_ms = (
            int(leader_exit["observed_at_ms"]) if leader_exit is not None else None
        )
        use_leader_exit = bool(
            leader_exit_ms is not None and leader_exit_ms <= time_stop_ms
        )
        target_exit_ms = leader_exit_ms if use_leader_exit else time_stop_ms
        dynamic_horizon_ms = max(0, int(target_exit_ms) - int(entry["ts_ms"]))
        trade, reason = execute_metaorder(
            metaorder,
            books,
            horizon_ms=dynamic_horizon_ms,
            direction_multiplier=int(direction_multiplier),
            require_causal_books=True,
        )
        if trade is None:
            counters[reason] = counters.get(reason, 0) + 1
            continue
        active_exit_times = [
            ts for ts in active_exit_times if ts > int(trade["entry_ts_ms"])
        ]
        if len(active_exit_times) >= MAX_OPEN_POSITIONS:
            counters["portfolio_capacity_rejected"] += 1
            continue
        if trade["trade_id"] in seen:
            counters["DUPLICATE_TRADE_ID_REJECTED"] = (
                counters.get("DUPLICATE_TRADE_ID_REJECTED", 0) + 1
            )
            continue
        seen.add(str(trade["trade_id"]))
        active_exit_times.append(int(trade["exit_ts_ms"]))
        trigger = "LEADER_REDUCE_OR_CLOSE" if use_leader_exit else "TIME_STOP"
        event_id = None
        event_action = None
        event_observed_ms = None
        if use_leader_exit and leader_exit is not None:
            event_id = str(
                leader_exit.get("event_id")
                or leader_exit.get("fill_id")
                or leader_exit.get("hash")
                or ""
            )
            event_action = str(leader_exit.get("action") or "").upper()
            event_observed_ms = int(leader_exit["observed_at_ms"])
        trades.append(
            {
                **trade,
                "mechanism": MECHANISM,
                "walk_forward_segment": "train",
                "required_observed_fills": int(required_observed_fills),
                "max_hold_ms": int(horizon_ms),
                "exit_policy": EXIT_POLICY,
                "exit_trigger": trigger,
                "leader_exit_action": event_action,
                "leader_exit_event_id": event_id,
                "leader_exit_observed_at_ms": event_observed_ms,
                "leader_exit_to_book_ms": (
                    int(trade["exit_ts_ms"]) - event_observed_ms
                    if event_observed_ms is not None
                    else None
                ),
                "sizing_policy": "FIXED_PAPER_NOTIONAL_USD",
                "paper_read_only": True,
                "real_execution": False,
            }
        )
        counters["completed_positions"] += 1
        counters[trigger] = counters.get(trigger, 0) + 1
    return trades, counters


def replay_lifecycle_train(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, Sequence[Mapping[str, Any]]],
    leader_events: Sequence[Mapping[str, Any]],
    *,
    required_observed_fills: int,
    horizon_ms: int,
    train_start_ms: int | None,
    train_end_ms: int | None,
    direction_multiplier: int = 1,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rejoue une variante fermée sur les seules bornes TRAIN fournies."""

    continuations, selection_audit = select_observed_continuations(
        metaorders,
        required_observed_fills=int(required_observed_fills),
    )
    exit_index, exit_audit = index_causal_leader_exits(leader_events)
    if (
        train_start_ms is None
        or train_end_ms is None
        or int(train_end_ms) < int(train_start_ms)
    ):
        return [], {
            "selection": selection_audit,
            "leader_exits": exit_audit,
            "replay": {
                "metaorders_considered": 0,
                "completed_positions": 0,
                "INVALID_OR_MISSING_TRAIN_BOUNDS": len(continuations),
            },
        }
    trades, replay_audit = _replay_selected(
        continuations,
        books_by_coin,
        exit_index,
        required_observed_fills=int(required_observed_fills),
        horizon_ms=int(horizon_ms),
        train_start_ms=int(train_start_ms),
        train_end_ms=int(train_end_ms),
        direction_multiplier=int(direction_multiplier),
    )
    return trades, {
        "selection": selection_audit,
        "leader_exits": exit_audit,
        "replay": replay_audit,
        "train_start_ms": int(train_start_ms),
        "train_end_ms": int(train_end_ms),
        "direction_multiplier": 1 if int(direction_multiplier) >= 0 else -1,
    }


def explore_copy_vault_v5_train(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, Sequence[Mapping[str, Any]]],
    leader_events: Sequence[Mapping[str, Any]],
    *,
    input_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Explore N fills x max-hold sans ouvrir validation/OOS/forward."""

    ordered = sorted(
        [dict(row) for row in metaorders],
        key=lambda row: (
            int(row.get("signal_ts_ms") or 0),
            str(row.get("metaorder_id") or ""),
        ),
    )
    exit_index, exit_audit = index_causal_leader_exits(leader_events)
    grid = [
        (required, int(horizon))
        for required in REQUIRED_OBSERVED_FILLS
        for horizon in HORIZONS_MS
    ]
    trial_count = len(grid)
    variants: list[dict[str, Any]] = []
    for required, horizon in grid:
        continuations, selection_audit = select_observed_continuations(
            ordered,
            required_observed_fills=required,
        )
        bounds = temporal_bounds(
            continuations,
            purge_ms=COPY_DELAY_MS + int(horizon) + MAX_TARGET_LAG_MS,
        )
        train_start_ms = bounds.get("train_start_ms")
        train_end_ms = bounds.get("train_end_ms")
        if (
            train_start_ms is not None
            and train_end_ms is not None
            and int(train_end_ms) >= int(train_start_ms)
        ):
            trades, replay_audit = _replay_selected(
                continuations,
                books_by_coin,
                exit_index,
                required_observed_fills=required,
                horizon_ms=horizon,
                train_start_ms=int(train_start_ms),
                train_end_ms=int(train_end_ms),
                direction_multiplier=1,
            )
            placebo_trades, placebo_audit = _replay_selected(
                continuations,
                books_by_coin,
                exit_index,
                required_observed_fills=required,
                horizon_ms=horizon,
                train_start_ms=int(train_start_ms),
                train_end_ms=int(train_end_ms),
                direction_multiplier=-1,
            )
        else:
            replay_audit = {
                "metaorders_considered": 0,
                "completed_positions": 0,
                "INVALID_OR_MISSING_TRAIN_BOUNDS": len(continuations),
            }
            placebo_audit = dict(replay_audit)
            trades = []
            placebo_trades = []
        assessment = assess_train_variant(
            trades,
            placebo_trades,
            trial_count=trial_count,
        )
        variants.append(
            {
                "required_observed_fills": required,
                "max_hold_ms": horizon,
                "bounds": bounds,
                "selection_audit": selection_audit,
                "replay_audit": replay_audit,
                "placebo_replay_audit": placebo_audit,
                **assessment,
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
            "required_observed_fills": selected["required_observed_fills"],
            "max_hold_ms": selected["max_hold_ms"],
            "copy_delay_ms": COPY_DELAY_MS,
            "notional_usd": NOTIONAL_USD,
            "exit_policy": EXIT_POLICY,
            "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        }
        if selected
        else None
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "mechanism": MECHANISM,
        "status": (
            "TRAIN_ELIGIBLE_TO_FREEZE" if selected else "NO_ROBUST_TRAIN_CANDIDATE"
        ),
        "selection_eligible": selected is not None,
        "physical_freeze_allowed": selected is not None,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_evaluated": False,
        "input_metaorders": len(ordered),
        "input_audit": dict(input_audit or {}),
        "leader_exit_audit": exit_audit,
        "fixed_grid": {
            "required_observed_fills": list(REQUIRED_OBSERVED_FILLS),
            "max_hold_ms": [int(value) for value in HORIZONS_MS],
            "trial_count": trial_count,
        },
        "exit_contract": {
            "policy": EXIT_POLICY,
            "leader_exit_actions": sorted(LEADER_EXIT_ACTIONS),
            "leader_exit_reaction_delay_ms": 0,
            "fallback": "FROZEN_TIME_STOP",
            "continuous_causal_book_required": True,
        },
        "cost_contract": {
            "notional_usd": NOTIONAL_USD,
            "executable_bbo_entry_exit": True,
            "canonical_fees_spread_latency_capacity": True,
            "liquidatable_net_required": True,
        },
        "selected": selected,
        "diagnostic_best_train_variant": diagnostic_best,
        "freeze_candidate": freeze_candidate,
        "freeze_candidate_sha256": (
            stable_hash(freeze_candidate) if freeze_candidate else None
        ),
        "variants": variants,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "EXIT_POLICY",
    "MECHANISM",
    "SCHEMA_VERSION",
    "explore_copy_vault_v5_train",
    "index_causal_leader_exits",
    "replay_lifecycle_train",
]
