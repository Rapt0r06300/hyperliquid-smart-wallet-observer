"""Frozen Copy-Vault V21 validation/OOS/forward evaluator.

The policy is immutable after the physical freeze.  This module never tunes on
held-out rows and never exposes a real execution surface.  Validation is opened
first; OOS is opened only if validation passes; physical forward is opened only
if OOS passes.  All fills remain PAPER/READ-ONLY and use recorded causal L2.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting import copy_vault_executable as cv
from hl_observer.backtesting.copy_vault_execution_math import (
    _book_side,
    _walk_base_quantity,
)
from hl_observer.backtesting.copy_vault_protocol import (
    COPY_DELAY_MS,
    MAX_REFERENCE_LAG_MS,
    MAX_TARGET_LAG_MS,
)
from hl_observer.backtesting.copy_vault_v4_train import assess_train_variant
from hl_observer.config.frais_venues import frais_taker_bps
from hl_observer.simulation.economic_freeze_registry import parameter_hash

SCHEMA_VERSION = "hypersmart.copy_vault_v21_frozen_evaluation.v1"
PROTOCOL = "copy_v21_entry_capacity_daily_lock_v1"
FROZEN_COPY_DELAY_MS = 60_000
FROZEN_MAX_REFERENCE_LAG_MS = 30_000
FROZEN_MAX_TARGET_LAG_MS = 30_000


def _first_action(metaorder: Mapping[str, Any]) -> str:
    members = list(metaorder.get("member_events") or ())
    if members and isinstance(members[0], Mapping):
        return str(members[0].get("action") or "").strip().upper()
    return str(metaorder.get("action") or "").strip().upper()


def _first_fill_notional_usd(metaorder: Mapping[str, Any]) -> float:
    members = list(metaorder.get("member_events") or ())
    if not members or not isinstance(members[0], Mapping):
        return 0.0
    try:
        return float(members[0].get("taille_usd") or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _reference_depth_features(
    metaorder: Mapping[str, Any],
    rows: Sequence[Mapping[str, Any]],
) -> tuple[float, float] | None:
    if not rows:
        return None
    timestamps = [int(row["ts_ms"]) for row in rows]
    signal_ms = int(metaorder["signal_ts_ms"])
    index = bisect.bisect_left(timestamps, signal_ms)
    if index >= len(rows) or timestamps[index] - signal_ms > FROZEN_MAX_REFERENCE_LAG_MS:
        return None
    row = rows[index]
    bids = list(row.get("bids5") or ())
    asks = list(row.get("asks5") or ())
    if not bids or not asks:
        return None
    bid_usd = sum(float(level[0]) * float(level[1]) for level in bids if len(level) >= 2)
    ask_usd = sum(float(level[0]) * float(level[1]) for level in asks if len(level) >= 2)
    total = bid_usd + ask_usd
    direction = int(metaorder.get("direction") or 0)
    two_sided_capacity = min(bid_usd, ask_usd)
    if total <= 0.0 or two_sided_capacity <= 0.0 or direction not in (-1, 1):
        return None
    return direction * (bid_usd - ask_usd) / total, two_sided_capacity


def _executable_net_bps(
    trade: Mapping[str, Any],
    book: Mapping[str, Any],
) -> float | None:
    direction = int(trade["direction"])
    top = float(book["bid"] if direction > 0 else book["ask"])
    levels = _book_side(
        book,
        "bids5" if direction > 0 else "asks5",
        expected_best=top,
        descending=direction > 0,
    )
    if levels is None:
        return None
    exit_price = _walk_base_quantity(levels, float(trade["quantity"]))
    if exit_price is None:
        return None
    quantity = float(trade["quantity"])
    entry_price = float(trade["entry_price"])
    fee_bps = frais_taker_bps("HYPERLIQUID")
    fees = (
        abs(quantity * entry_price) + abs(quantity * exit_price)
    ) * fee_bps / 10_000.0
    net = quantity * direction * (exit_price - entry_price) - fees
    notional = float(trade["notional_usd"])
    return net / notional * 10_000.0 if notional > 0.0 else None


def _apply_risk_exit(
    trade: Mapping[str, Any],
    metaorder: Mapping[str, Any],
    books: list[dict[str, Any]],
    *,
    stop_loss_bps: float,
    take_profit_bps: float,
    horizon_ms: int,
) -> tuple[dict[str, Any], str]:
    entry_ms = int(trade["entry_ts_ms"])
    fallback_exit_ms = int(trade["exit_ts_ms"])
    timestamps = [int(row["ts_ms"]) for row in books]
    start = bisect.bisect_right(timestamps, entry_ms)
    end = bisect.bisect_right(timestamps, fallback_exit_ms)
    trigger_book: Mapping[str, Any] | None = None
    trigger: str | None = None
    for book in books[start:end]:
        net_bps = _executable_net_bps(trade, book)
        if net_bps is None:
            continue
        if net_bps <= -abs(stop_loss_bps):
            trigger_book = book
            trigger = "EXECUTABLE_NET_STOP"
            break
        if net_bps >= abs(take_profit_bps):
            trigger_book = book
            trigger = "EXECUTABLE_NET_TAKE_PROFIT"
            break
    if trigger_book is None:
        return {
            **dict(trade),
            "risk_exit_policy": "FIRST_EXECUTABLE_NET_STOP_OR_TAKE_PROFIT",
            "risk_stop_loss_bps": float(stop_loss_bps),
            "risk_take_profit_bps": float(take_profit_bps),
            "risk_exit_trigger": "LIFECYCLE_FALLBACK",
        }, "LIFECYCLE_FALLBACK"

    direction_multiplier = (
        1 if int(trade["direction"]) == int(metaorder["direction"]) else -1
    )
    dynamic_horizon = int(trigger_book["ts_ms"]) - entry_ms
    adjusted, reason = cv.execute_metaorder(
        metaorder,
        books,
        horizon_ms=dynamic_horizon,
        direction_multiplier=direction_multiplier,
        copy_delay_ms=FROZEN_COPY_DELAY_MS,
        max_reference_lag_ms=FROZEN_MAX_REFERENCE_LAG_MS,
        max_target_lag_ms=FROZEN_MAX_TARGET_LAG_MS,
        notional_usd=float(trade["notional_usd"]),
        require_causal_books=True,
    )
    if adjusted is None:
        return {
            **dict(trade),
            "risk_exit_policy": "FIRST_EXECUTABLE_NET_STOP_OR_TAKE_PROFIT",
            "risk_stop_loss_bps": float(stop_loss_bps),
            "risk_take_profit_bps": float(take_profit_bps),
            "risk_exit_trigger": "RECONSTRUCTION_REFUSED_FALLBACK",
            "risk_exit_reconstruction_reason": reason,
        }, "RECONSTRUCTION_REFUSED_FALLBACK"
    return {
        **adjusted,
        "risk_exit_policy": "FIRST_EXECUTABLE_NET_STOP_OR_TAKE_PROFIT",
        "risk_stop_loss_bps": float(stop_loss_bps),
        "risk_take_profit_bps": float(take_profit_bps),
        "risk_exit_trigger": str(trigger),
    }, str(trigger)


def _mean_daily(statistics: Mapping[str, Any]) -> float | None:
    values = [float(value) for value in (statistics.get("daily_net_pnl_usd") or ())]
    return sum(values) / len(values) if values else None


def _verified_freeze(raw: Mapping[str, Any]) -> dict[str, Any]:
    freeze = raw.get("freeze") if isinstance(raw.get("freeze"), Mapping) else raw
    if not isinstance(freeze, Mapping):
        raise ValueError("COPY_V21_FREEZE_MISSING")
    row = dict(freeze)
    params = row.get("parameters")
    if (
        row.get("schema_version") != "hypersmart.economic_parameter_freeze.v1"
        or row.get("family") != "copy_vault"
        or row.get("selected_before_final_evaluation") is not True
        or not isinstance(params, Mapping)
    ):
        raise ValueError("COPY_V21_FREEZE_INVALID")
    parameters = dict(params)
    if parameters.get("protocol") != PROTOCOL:
        raise ValueError("COPY_V21_PROTOCOL_MISMATCH")
    if parameters.get("paper_read_only") is not True or parameters.get("real_execution") is not False:
        raise ValueError("COPY_V21_SAFETY_CONTRACT_MISMATCH")
    if parameter_hash(parameters) != str(row.get("parameters_sha256") or ""):
        raise ValueError("COPY_V21_FREEZE_HASH_MISMATCH")
    if int(row.get("frozen_at_ms") or 0) <= 0:
        raise ValueError("COPY_V21_FREEZE_TIMESTAMP_INVALID")
    if (
        int(COPY_DELAY_MS) != FROZEN_COPY_DELAY_MS
        or int(MAX_REFERENCE_LAG_MS) != FROZEN_MAX_REFERENCE_LAG_MS
        or int(MAX_TARGET_LAG_MS) != FROZEN_MAX_TARGET_LAG_MS
    ):
        raise ValueError("COPY_V21_EXECUTION_PROTOCOL_DRIFT")
    return row


def _segment_candidates(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    *,
    start_ms: int,
    end_ms: int | None,
    minimum_leader_fill_notional_usd: float,
    signed_depth_imbalance_minimum: float,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    audit: dict[str, int] = defaultdict(int)
    candidates: list[dict[str, Any]] = []
    for raw in metaorders:
        signal_ms = int(raw.get("signal_ts_ms") or 0)
        if signal_ms < int(start_ms) or (end_ms is not None and signal_ms > int(end_ms)):
            continue
        audit["SIGNALS_IN_SEGMENT"] += 1
        row = dict(raw)
        coin = str(row.get("coin") or "")
        if _first_action(row) != "ADD":
            audit["NON_ADD_REJECTED"] += 1
            continue
        books = books_by_coin.get(coin, [])
        features = _reference_depth_features(row, books)
        if features is None:
            audit["REFERENCE_DEPTH_FEATURE_UNMEASURABLE"] += 1
            continue
        row["signed_reference_depth_imbalance"] = features[0]
        row["reference_two_sided_capacity_usd"] = features[1]
        if float(features[0]) < float(signed_depth_imbalance_minimum):
            audit["DEPTH_IMBALANCE_REJECTED"] += 1
            continue
        first_notional = _first_fill_notional_usd(row)
        if first_notional < float(minimum_leader_fill_notional_usd):
            audit["LEADER_FILL_NOTIONAL_REJECTED"] += 1
            continue
        row["first_fill_leader_notional_usd"] = first_notional
        candidates.append(row)
        audit["FIXED_POLICY_CANDIDATE"] += 1
    return candidates, dict(audit)


def _settle(
    candidates: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    *,
    segment: str,
    params: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    audit: dict[str, int] = defaultdict(int)
    trades: list[dict[str, Any]] = []
    placebos: list[dict[str, Any]] = []
    vault_day: dict[tuple[str, int], int] = defaultdict(int)
    coin_day: dict[tuple[str, int], int] = defaultdict(int)
    active_exit_times: list[int] = []

    for metaorder in sorted(
        candidates,
        key=lambda row: (int(row["signal_ts_ms"]), str(row["metaorder_id"])),
    ):
        signal_ms = int(metaorder["signal_ts_ms"])
        day = signal_ms // 86_400_000
        vault_key = (str(metaorder["vault"]), day)
        coin_key = (str(metaorder["coin"]), day)
        if vault_day[vault_key] >= int(params["vault_daily_limit"]):
            audit["VAULT_DAILY_BUDGET_REJECTED"] += 1
            continue
        if coin_day[coin_key] >= int(params["coin_daily_limit"]):
            audit["COIN_DAILY_BUDGET_REJECTED"] += 1
            continue
        active_exit_times = [value for value in active_exit_times if value > signal_ms]
        if len(active_exit_times) >= int(params["max_open_positions"]):
            audit["PORTFOLIO_CAPACITY_REJECTED"] += 1
            continue

        realized_today = sum(
            float(trade["net_pnl_usd"])
            for trade in trades
            if int(trade["exit_ts_ms"]) <= signal_ms
            and int(trade["exit_ts_ms"]) // 86_400_000 == day
        )
        locked = realized_today >= float(params["daily_profit_lock_usd"])
        notional_usd = (
            float(params["probe_notional_usd"])
            if locked
            else float(params["core_notional_usd"])
        )
        sizing_state = (
            "POST_LOCK_NEW_VAULT_PROBE"
            if locked
            else "PRE_LOCK_DEPTH_CAPPED_CORE"
        )
        books = list(books_by_coin.get(str(metaorder["coin"]), []))
        actual, actual_reason = cv.execute_metaorder(
            metaorder,
            books,
            horizon_ms=int(params["horizon_ms"]),
            direction_multiplier=1,
            copy_delay_ms=FROZEN_COPY_DELAY_MS,
            max_reference_lag_ms=FROZEN_MAX_REFERENCE_LAG_MS,
            max_target_lag_ms=FROZEN_MAX_TARGET_LAG_MS,
            notional_usd=notional_usd,
            require_causal_books=True,
        )
        placebo, placebo_reason = cv.execute_metaorder(
            metaorder,
            books,
            horizon_ms=int(params["horizon_ms"]),
            direction_multiplier=-1,
            copy_delay_ms=FROZEN_COPY_DELAY_MS,
            max_reference_lag_ms=FROZEN_MAX_REFERENCE_LAG_MS,
            max_target_lag_ms=FROZEN_MAX_TARGET_LAG_MS,
            notional_usd=notional_usd,
            require_causal_books=True,
        )
        if actual is None or placebo is None:
            if actual is None:
                audit[f"ACTUAL_PROVENANCE_REFUSAL_{actual_reason}"] += 1
            if placebo is None:
                audit[f"PLACEBO_PROVENANCE_REFUSAL_{placebo_reason}"] += 1
            audit["INCOMPLETE_EPISODE_REJECTED"] += 1
            continue

        actual, actual_trigger = _apply_risk_exit(
            actual,
            metaorder,
            books,
            stop_loss_bps=float(params["stop_loss_bps"]),
            take_profit_bps=float(params["take_profit_bps"]),
            horizon_ms=int(params["horizon_ms"]),
        )
        placebo, placebo_trigger = _apply_risk_exit(
            placebo,
            metaorder,
            books,
            stop_loss_bps=float(params["stop_loss_bps"]),
            take_profit_bps=float(params["take_profit_bps"]),
            horizon_ms=int(params["horizon_ms"]),
        )
        common = {
            "mechanism": "copy_v21_entry_capacity_daily_lock",
            "walk_forward_segment": segment,
            "signal_action": _first_action(metaorder),
            "first_fill_leader_notional_usd": _first_fill_notional_usd(metaorder),
            "signed_reference_depth_imbalance": float(metaorder["signed_reference_depth_imbalance"]),
            "reference_two_sided_capacity_usd": float(metaorder["reference_two_sided_capacity_usd"]),
            "sizing_state": sizing_state,
            "realized_daily_pnl_before_entry_usd": realized_today,
            "daily_profit_lock_usd": float(params["daily_profit_lock_usd"]),
            "risk_exit_trigger": actual_trigger,
            "placebo_risk_exit_trigger": placebo_trigger,
            "frozen_policy": True,
            "retuned_on_heldout": False,
            "paper_read_only": True,
            "real_execution": False,
        }
        trades.append({**actual, **common})
        placebos.append({**placebo, **common})
        vault_day[vault_key] += 1
        coin_day[coin_key] += 1
        active_exit_times.append(int(actual["exit_ts_ms"]))
        audit["ADMITTED_CLOSED_POSITION"] += 1

    return trades, placebos, dict(audit)


def _evaluate_segment(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    *,
    segment: str,
    start_ms: int,
    end_ms: int | None,
    params: Mapping[str, Any],
) -> dict[str, Any]:
    candidates, candidate_audit = _segment_candidates(
        metaorders,
        books_by_coin,
        start_ms=start_ms,
        end_ms=end_ms,
        minimum_leader_fill_notional_usd=float(params["minimum_leader_fill_notional_usd"]),
        signed_depth_imbalance_minimum=float(params["signed_depth_imbalance_minimum"]),
    )
    trades, placebos, replay_audit = _settle(
        candidates,
        books_by_coin,
        segment=segment,
        params=params,
    )
    assessment = assess_train_variant(
        trades,
        placebos,
        trial_count=int(params["bonferroni_trial_count"]),
    )
    daily_mean = _mean_daily(assessment["statistics"])
    reasons = list(assessment["reasons"])
    if daily_mean is None or daily_mean < float(params["daily_profit_lock_usd"]):
        reasons.append("DAILY_MEAN_NET_BELOW_4_USD")
    return {
        "segment": segment,
        "status": "PASS" if not reasons else "FAIL",
        "eligible": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "start_ms": int(start_ms),
        "end_ms": int(end_ms) if end_ms is not None else None,
        "candidate_count": len(candidates),
        "candidate_audit": candidate_audit,
        "replay_audit": replay_audit,
        **assessment,
        "daily_mean_net_pnl_usd": daily_mean,
        "trades": trades,
        "placebos": placebos,
        "heldout_evaluated": True,
        "retuned_on_heldout": False,
        "paper_read_only": True,
        "real_execution": False,
        "carry_pnl_usd": 0.0,
    }


def evaluate_frozen_v21_segment(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    freeze_payload: Mapping[str, Any],
    *,
    segment: str,
) -> dict[str, Any]:
    """Reproduce one named segment with the immutable V21 policy."""
    freeze = _verified_freeze(freeze_payload)
    params = dict(freeze["parameters"])
    bounds = dict(params.get("bounds") or {})
    selected = str(segment).strip().lower()
    if selected == "train":
        start_ms = int(bounds["train_start_ms"])
        end_ms: int | None = int(bounds["train_end_ms"])
    elif selected == "validation":
        start_ms = int(bounds["validation_start_ms"])
        end_ms = int(bounds["validation_end_ms"])
    elif selected == "oos":
        start_ms = int(bounds["oos_start_ms"])
        end_ms = int(bounds["oos_end_ms"])
    elif selected == "forward":
        start_ms = int(freeze["frozen_at_ms"]) + 1
        end_ms = None
    else:
        raise ValueError(f"unsupported COPY_V21 segment: {segment!r}")
    return _evaluate_segment(
        metaorders,
        books_by_coin,
        segment=selected,
        start_ms=start_ms,
        end_ms=end_ms,
        params=params,
    )


def evaluate_frozen_v21(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    freeze_payload: Mapping[str, Any],
    *,
    input_audit: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    freeze = _verified_freeze(freeze_payload)
    params = dict(freeze["parameters"])
    bounds = dict(params.get("bounds") or {})

    validation = _evaluate_segment(
        metaorders,
        books_by_coin,
        segment="validation",
        start_ms=int(bounds["validation_start_ms"]),
        end_ms=int(bounds["validation_end_ms"]),
        params=params,
    )
    if validation["eligible"]:
        oos = _evaluate_segment(
            metaorders,
            books_by_coin,
            segment="oos",
            start_ms=int(bounds["oos_start_ms"]),
            end_ms=int(bounds["oos_end_ms"]),
            params=params,
        )
    else:
        oos = {
            "segment": "oos",
            "status": "BLOCKED_BY_VALIDATION",
            "eligible": False,
            "heldout_evaluated": False,
            "retuned_on_heldout": False,
            "paper_read_only": True,
            "real_execution": False,
            "carry_pnl_usd": 0.0,
        }

    if validation["eligible"] and oos.get("eligible") is True:
        forward = _evaluate_segment(
            metaorders,
            books_by_coin,
            segment="forward",
            start_ms=int(freeze["frozen_at_ms"]) + 1,
            end_ms=None,
            params=params,
        )
    else:
        forward = {
            "segment": "forward",
            "status": "BLOCKED_BY_OOS",
            "eligible": False,
            "heldout_evaluated": False,
            "retuned_on_heldout": False,
            "paper_read_only": True,
            "real_execution": False,
            "carry_pnl_usd": 0.0,
        }

    proven = bool(
        validation.get("eligible") is True
        and oos.get("eligible") is True
        and forward.get("eligible") is True
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "family": "copy_vault",
        "protocol": PROTOCOL,
        "objective_net_usd_per_day": float(params["daily_profit_lock_usd"]),
        "objective_status": "ATTEINT" if proven else "NON_PROUVE",
        "economically_proven": proven,
        "selection_scope": "IMMUTABLE_FROZEN_POLICY_SEQUENTIAL_HELDOUT",
        "heldout_used_for_retuning": False,
        "frozen_at_ms": int(freeze["frozen_at_ms"]),
        "parameters_sha256": str(freeze["parameters_sha256"]),
        "parameters": params,
        "input_audit": dict(input_audit or {}),
        "validation": validation,
        "oos": oos,
        "forward": forward,
        "carry_pnl_usd": 0.0,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "PROTOCOL",
    "SCHEMA_VERSION",
    "evaluate_frozen_v21",
    "evaluate_frozen_v21_segment",
]
