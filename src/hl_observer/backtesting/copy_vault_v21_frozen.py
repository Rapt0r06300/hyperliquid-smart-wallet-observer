"""Frozen Copy-Vault V21 validation/OOS/forward evaluator.

The policy is immutable after the physical freeze.  This module never tunes on
held-out rows and never exposes a real execution surface.  Validation is opened
first; OOS is opened only if validation passes; physical forward is opened only
if OOS passes.  All fills remain PAPER/READ-ONLY and use recorded causal L2.
"""
from __future__ import annotations

import bisect
import math
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
    MAX_GROSS_EXPOSURE_USD,
    MAX_REFERENCE_LAG_MS,
    MAX_TARGET_LAG_MS,
    PAPER_EQUITY_USD,
)
from hl_observer.backtesting.copy_vault_v4_train import assess_train_variant
from hl_observer.backtesting.train_statistics import (
    UTC_DAY_MS,
    summarize_complete_utc_days,
)
from hl_observer.config.frais_venues import frais_taker_bps
from hl_observer.simulation.economic_freeze_registry import parameter_hash

SCHEMA_VERSION = "hypersmart.copy_vault_v21_frozen_evaluation.v3"
PROTOCOL = "copy_v21_entry_capacity_daily_lock_v1"
REFERENCE_DAILY_OBJECTIVE_USD = 5.0
FROZEN_COPY_DELAY_MS = 60_000
FROZEN_MAX_REFERENCE_LAG_MS = 30_000
FROZEN_MAX_TARGET_LAG_MS = 30_000
CAPACITY_SCENARIOS_USD = (10.0, 50.0, 100.0, 200.0, 400.0, 1_000.0, 2_000.0, 5_000.0, 10_000.0)


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
    if any(right < left for left, right in zip(timestamps, timestamps[1:], strict=False)):
        return None
    signal_ms = int(metaorder["signal_ts_ms"])
    index = bisect.bisect_right(timestamps, signal_ms) - 1
    if index < 0 or signal_ms - timestamps[index] > FROZEN_MAX_REFERENCE_LAG_MS:
        return None
    row = rows[index]
    if row.get("causal_observation") is not True:
        return None
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
    copy_delay_ms: int = FROZEN_COPY_DELAY_MS,
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
        copy_delay_ms=copy_delay_ms,
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


def _reference_objective_status(*segments: Mapping[str, Any]) -> str:
    daily_means = [segment.get("daily_mean_net_pnl_usd") for segment in segments]
    if not daily_means or any(value is None for value in daily_means):
        return "UNMEASURABLE"
    return (
        "ATTEINT"
        if all(float(value) >= REFERENCE_DAILY_OBJECTIVE_USD for value in daily_means)
        else "NON_ATTEINT"
    )


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
    required_parameters = {
        "training_selection_eligible",
        "minimum_leader_fill_notional_usd",
        "signed_depth_imbalance_minimum",
        "core_notional_usd",
        "probe_notional_usd",
        "daily_profit_lock_usd",
        "stop_loss_bps",
        "take_profit_bps",
        "horizon_ms",
        "vault_daily_limit",
        "coin_daily_limit",
        "max_open_positions",
        "bonferroni_trial_count",
        "bounds",
    }
    if (
        not required_parameters.issubset(parameters)
        or parameters.get("training_selection_eligible") is not True
    ):
        raise ValueError("COPY_V21_FREEZE_PARAMETERS_INVALID")
    positive_parameters = (
        "minimum_leader_fill_notional_usd",
        "daily_profit_lock_usd",
        "stop_loss_bps",
        "take_profit_bps",
        "horizon_ms",
        "vault_daily_limit",
        "coin_daily_limit",
        "max_open_positions",
        "bonferroni_trial_count",
    )
    try:
        positive_values = [float(parameters[name]) for name in positive_parameters]
        signed_imbalance_minimum = float(parameters["signed_depth_imbalance_minimum"])
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("COPY_V21_FREEZE_PARAMETERS_INVALID") from exc
    if (
        any(not math.isfinite(value) or value <= 0.0 for value in positive_values)
        or not math.isfinite(signed_imbalance_minimum)
        or not -1.0 <= signed_imbalance_minimum <= 1.0
        or any(not value.is_integer() for value in positive_values[-5:])
    ):
        raise ValueError("COPY_V21_FREEZE_PARAMETERS_INVALID")
    for name in ("core_notional_usd", "probe_notional_usd"):
        try:
            notional = float(parameters[name])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError("COPY_V21_PAPER_NOTIONAL_INVALID") from exc
        if (
            not math.isfinite(notional)
            or notional <= 0.0
            or notional > MAX_GROSS_EXPOSURE_USD
        ):
            raise ValueError("COPY_V21_PAPER_GROSS_EXPOSURE_LIMIT_EXCEEDED")
    try:
        frozen_at_ms = int(row.get("frozen_at_ms") or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("COPY_V21_FREEZE_TIMESTAMP_INVALID") from exc
    if frozen_at_ms <= 0:
        raise ValueError("COPY_V21_FREEZE_TIMESTAMP_INVALID")
    try:
        bounds = parameters["bounds"]
        if not isinstance(bounds, Mapping):
            raise TypeError
        train_start_ms = int(bounds["train_start_ms"])
        train_end_ms = int(bounds["train_end_ms"])
        validation_start_ms = int(bounds["validation_start_ms"])
        validation_end_ms = int(bounds["validation_end_ms"])
        oos_start_ms = int(bounds["oos_start_ms"])
        oos_end_ms = int(bounds["oos_end_ms"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ValueError("COPY_V21_FREEZE_BOUNDS_INVALID") from exc
    if (
        min(
            train_start_ms,
            train_end_ms,
            validation_start_ms,
            validation_end_ms,
            oos_start_ms,
            oos_end_ms,
        ) <= 0
        or train_end_ms < train_start_ms
        or validation_start_ms <= train_end_ms
        or validation_end_ms < validation_start_ms
        or oos_start_ms <= validation_end_ms
        or oos_end_ms < oos_start_ms
        or frozen_at_ms <= oos_end_ms
    ):
        raise ValueError("COPY_V21_FREEZE_BOUNDS_INVALID")
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
    capital_scenario_usd: float | None = None,
    execution_delay_ms: int = FROZEN_COPY_DELAY_MS,
    fee_bps: float | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    if capital_scenario_usd is not None:
        try:
            capital_scenario_usd = float(capital_scenario_usd)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("COPY_V21_CAPITAL_SCENARIO_INVALID") from exc
        if not math.isfinite(capital_scenario_usd) or capital_scenario_usd <= 0.0:
            raise ValueError("COPY_V21_CAPITAL_SCENARIO_INVALID")
        sizing_scale = capital_scenario_usd / float(PAPER_EQUITY_USD)
    else:
        sizing_scale = 1.0
    gross_exposure_limit = (
        float(capital_scenario_usd)
        if capital_scenario_usd is not None
        else float(MAX_GROSS_EXPOSURE_USD)
    )
    scenario_params = dict(params)
    scenario_params["core_notional_usd"] = float(params["core_notional_usd"]) * sizing_scale
    scenario_params["probe_notional_usd"] = float(params["probe_notional_usd"]) * sizing_scale
    scenario_params["daily_profit_lock_usd"] = float(params["daily_profit_lock_usd"]) * sizing_scale
    audit: dict[str, int] = defaultdict(int)
    trades: list[dict[str, Any]] = []
    placebos: list[dict[str, Any]] = []
    vault_day: dict[tuple[str, int], int] = defaultdict(int)
    coin_day: dict[tuple[str, int], int] = defaultdict(int)
    active_positions: list[tuple[int, float]] = []

    for metaorder in sorted(
        candidates,
        key=lambda row: (int(row["signal_ts_ms"]), str(row["metaorder_id"])),
    ):
        signal_ms = int(metaorder["signal_ts_ms"])
        day = signal_ms // 86_400_000
        vault_key = (str(metaorder["vault"]), day)
        coin_key = (str(metaorder["coin"]), day)
        if vault_day[vault_key] >= int(scenario_params["vault_daily_limit"]):
            audit["VAULT_DAILY_BUDGET_REJECTED"] += 1
            continue
        if coin_day[coin_key] >= int(scenario_params["coin_daily_limit"]):
            audit["COIN_DAILY_BUDGET_REJECTED"] += 1
            continue
        active_positions = [
            (exit_ms, notional)
            for exit_ms, notional in active_positions
            if exit_ms > signal_ms
        ]
        if len(active_positions) >= int(scenario_params["max_open_positions"]):
            audit["PORTFOLIO_CAPACITY_REJECTED"] += 1
            continue

        realized_today = sum(
            float(trade["net_pnl_usd"])
            for trade in trades
            if int(trade["exit_ts_ms"]) <= signal_ms
            and int(trade["exit_ts_ms"]) // 86_400_000 == day
        )
        locked = realized_today >= float(scenario_params["daily_profit_lock_usd"])
        notional_usd = (
            float(scenario_params["probe_notional_usd"])
            if locked
            else float(scenario_params["core_notional_usd"])
        )
        active_gross_usd = sum(notional for _, notional in active_positions)
        if (
            not math.isfinite(notional_usd)
            or notional_usd <= 0.0
            or active_gross_usd + notional_usd > gross_exposure_limit + 1e-9
        ):
            audit["PAPER_GROSS_EXPOSURE_REJECTED"] += 1
            continue
        sizing_state = (
            "POST_LOCK_NEW_VAULT_PROBE"
            if locked
            else "PRE_LOCK_DEPTH_CAPPED_CORE"
        )
        books = list(books_by_coin.get(str(metaorder["coin"]), []))
        actual, actual_reason = cv.execute_metaorder(
            metaorder,
            books,
            horizon_ms=int(scenario_params["horizon_ms"]),
            direction_multiplier=1,
            copy_delay_ms=execution_delay_ms,
            max_reference_lag_ms=FROZEN_MAX_REFERENCE_LAG_MS,
            max_target_lag_ms=FROZEN_MAX_TARGET_LAG_MS,
            notional_usd=notional_usd,
            fee_bps=fee_bps,
            require_causal_books=True,
        )
        placebo, placebo_reason = cv.execute_metaorder(
            metaorder,
            books,
            horizon_ms=int(scenario_params["horizon_ms"]),
            direction_multiplier=-1,
            copy_delay_ms=execution_delay_ms,
            max_reference_lag_ms=FROZEN_MAX_REFERENCE_LAG_MS,
            max_target_lag_ms=FROZEN_MAX_TARGET_LAG_MS,
            notional_usd=notional_usd,
            fee_bps=fee_bps,
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
            stop_loss_bps=float(scenario_params["stop_loss_bps"]),
            take_profit_bps=float(scenario_params["take_profit_bps"]),
            horizon_ms=int(scenario_params["horizon_ms"]),
            copy_delay_ms=execution_delay_ms,
        )
        placebo, placebo_trigger = _apply_risk_exit(
            placebo,
            metaorder,
            books,
            stop_loss_bps=float(scenario_params["stop_loss_bps"]),
            take_profit_bps=float(scenario_params["take_profit_bps"]),
            horizon_ms=int(scenario_params["horizon_ms"]),
            copy_delay_ms=execution_delay_ms,
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
            "daily_profit_lock_usd": float(scenario_params["daily_profit_lock_usd"]),
            "risk_exit_trigger": actual_trigger,
            "placebo_risk_exit_trigger": placebo_trigger,
            "frozen_policy": True,
            "retuned_on_heldout": False,
            "paper_read_only": True,
            "real_execution": False,
        }
        if capital_scenario_usd is not None:
            common.update({
                "economic_scope": "DIAGNOSTIC_ONLY",
                "economically_proven": False,
                "capital_scenario_usd": capital_scenario_usd,
                "capital_scenario_sizing_scale": sizing_scale,
            })
        trades.append({**actual, **common})
        placebos.append({**placebo, **common})
        vault_day[vault_key] += 1
        coin_day[coin_key] += 1
        active_positions.append((int(actual["exit_ts_ms"]), notional_usd))
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
    capital_scenario_usd: float | None = None,
    execution_delay_ms: int = FROZEN_COPY_DELAY_MS,
    fee_bps: float | None = None,
    complete_utc_day_starts_ms: Sequence[object] | None = None,
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
        capital_scenario_usd=capital_scenario_usd,
        execution_delay_ms=execution_delay_ms,
        fee_bps=fee_bps,
    )
    assessment = assess_train_variant(
        trades,
        placebos,
        trial_count=int(params["bonferroni_trial_count"]),
    )
    daily_mean = _mean_daily(assessment["statistics"])
    fully_covered_days = None
    if complete_utc_day_starts_ms is not None:
        first_full_day = ((int(start_ms) + UTC_DAY_MS - 1) // UTC_DAY_MS) * UTC_DAY_MS
        fully_covered_days = []
        for day in complete_utc_day_starts_ms:
            if (
                isinstance(day, (int, float))
                and not isinstance(day, bool)
                and math.isfinite(day)
                and int(day) == day
                and (
                    int(day) < first_full_day
                    or (
                    end_ms is not None
                    and int(day) + UTC_DAY_MS - 1 > int(end_ms)
                    )
                )
            ):
                continue
            fully_covered_days.append(day)
    calendar_stats = summarize_complete_utc_days(
        trades,
        value_key="net_pnl_usd",
        timestamp_key="exit_ts_ms",
        complete_day_starts_ms=fully_covered_days,
    )
    reasons = list(assessment["reasons"])
    return {
        **assessment,
        "segment": segment,
        "status": "PASS" if not reasons else "FAIL",
        "eligible": not reasons,
        "reasons": list(dict.fromkeys(reasons)),
        "start_ms": int(start_ms),
        "end_ms": int(end_ms) if end_ms is not None else None,
        "candidate_count": len(candidates),
        "candidate_audit": candidate_audit,
        "replay_audit": replay_audit,
        "daily_mean_net_pnl_usd": calendar_stats["calendar_day_mean_net_pnl_usd"],
        "active_day_mean_net_pnl_usd": daily_mean,
        "daily_mean_net_pnl_scope": "COMPLETE_UTC_CALENDAR_DAYS",
        "calendar_day_statistics": calendar_stats,
        "trades": trades,
        "placebos": placebos,
        "heldout_evaluated": True,
        "retuned_on_heldout": False,
        "paper_read_only": True,
        "real_execution": False,
        "carry_pnl_usd": 0.0,
        "economic_scope": "DIAGNOSTIC_ONLY" if capital_scenario_usd is not None else "FROZEN_POLICY_EVALUATION",
        "economically_proven": False if capital_scenario_usd is not None else None,
    }


def evaluate_frozen_v21_segment(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    freeze_payload: Mapping[str, Any],
    *,
    segment: str,
    capital_scenario_usd: float | None = None,
    complete_utc_day_starts_ms: Sequence[object] | None = None,
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
        capital_scenario_usd=capital_scenario_usd,
        complete_utc_day_starts_ms=complete_utc_day_starts_ms,
    )


def evaluate_capacity_scenarios(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    freeze_payload: Mapping[str, Any],
    *,
    segment: str = "oos",
    capital_scenarios_usd: Sequence[float] = CAPACITY_SCENARIOS_USD,
) -> dict[str, Any]:
    """Replay the same frozen sizing rule across predeclared hypothetical capital caps."""
    scenarios = [float(value) for value in capital_scenarios_usd]
    if (
        not scenarios
        or any(not math.isfinite(value) or value <= 0.0 for value in scenarios)
        or len(set(scenarios)) != len(scenarios)
    ):
        raise ValueError("COPY_V21_CAPITAL_SCENARIOS_INVALID")
    rows = [
        evaluate_frozen_v21_segment(
            metaorders,
            books_by_coin,
            freeze_payload,
            segment=segment,
            capital_scenario_usd=capital,
        )
        for capital in scenarios
    ]
    return {
        "schema_version": "hypersmart.copy_vault_capacity_diagnostic.v1",
        "segment": str(segment).strip().lower(),
        "scope": "DIAGNOSTIC_ONLY",
        "economic_proof": False,
        "promotion_eligible": False,
        "capital_scenarios_usd": scenarios,
        "sizing_policy": "FROZEN_NOTIONAL_AND_DAILY_LOCK_SCALED_PROPORTIONALLY_TO_CAPITAL",
        "exposure_limit_policy": "GROSS_EXPOSURE_CAPPED_AT_SCENARIO_CAPITAL_NO_LEVERAGE_ASSUMED",
        "instrument_minimum_and_lot_rules": "NOT_EVALUATED_BY_THIS_DIAGNOSTIC",
        "promotion_blocker": "CAPACITY_SCENARIO_IS_NOT_ECONOMIC_PROOF",
        "scenarios": rows,
        "paper_read_only": True,
        "real_execution": False,
    }


def _stress_books(
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    *,
    spread_multiplier: float = 1.0,
    depth_multiplier: float = 1.0,
) -> dict[str, list[dict[str, Any]]]:
    if (
        not math.isfinite(float(spread_multiplier))
        or float(spread_multiplier) < 1.0
        or not math.isfinite(float(depth_multiplier))
        or not 0.0 < float(depth_multiplier) <= 1.0
    ):
        raise ValueError("COPY_V21_STRESS_MULTIPLIER_INVALID")
    stressed: dict[str, list[dict[str, Any]]] = {}
    for coin, books in books_by_coin.items():
        stressed_rows: list[dict[str, Any]] = []
        for raw in books:
            row = dict(raw)
            bids = list(row.get("bids5") or ())
            asks = list(row.get("asks5") or ())
            if not bids or not asks:
                stressed_rows.append(row)
                continue
            try:
                best_bid = float(bids[0][0])
                best_ask = float(asks[0][0])
                mid = (best_bid + best_ask) / 2.0
                if (
                    not math.isfinite(mid)
                    or mid <= 0.0
                    or best_ask <= best_bid
                ):
                    raise ValueError

                def transform(levels, *, is_bid: bool, midpoint: float):
                    output = []
                    for level in levels:
                        price, quantity = float(level[0]), float(level[1])
                        if (
                            not math.isfinite(price)
                            or price <= 0.0
                            or not math.isfinite(quantity)
                            or quantity <= 0.0
                        ):
                            raise ValueError
                        stressed_price = (
                            midpoint - (midpoint - price) * float(spread_multiplier)
                            if is_bid
                            else midpoint + (price - midpoint) * float(spread_multiplier)
                        )
                        output.append(
                            [stressed_price, quantity * float(depth_multiplier), *list(level[2:])]
                        )
                    return output

                row["bids5"] = transform(bids, is_bid=True, midpoint=mid)
                row["asks5"] = transform(asks, is_bid=False, midpoint=mid)
                row["bid"] = row["bids5"][0][0]
                row["ask"] = row["asks5"][0][0]
            except (IndexError, TypeError, ValueError, OverflowError) as exc:
                raise ValueError("COPY_V21_STRESS_BOOK_INVALID") from exc
            stressed_rows.append(row)
        stressed[str(coin)] = stressed_rows
    return stressed


def evaluate_stress_matrix(
    metaorders: Sequence[Mapping[str, Any]],
    books_by_coin: Mapping[str, list[dict[str, Any]]],
    freeze_payload: Mapping[str, Any],
    *,
    segment: str = "forward",
) -> dict[str, Any]:
    """Run fixed, labelled stresses through the same V21 execution path."""
    freeze = _verified_freeze(freeze_payload)
    canonical_fee_bps = float(frais_taker_bps("HYPERLIQUID"))
    scenarios: list[dict[str, Any]] = []
    definitions = [
        ("BASELINE_REFERENCE", {}, FROZEN_COPY_DELAY_MS, None),
        ("FEE_X2", {}, FROZEN_COPY_DELAY_MS, canonical_fee_bps * 2.0),
        ("SPREAD_X2", {"spread_multiplier": 2.0}, FROZEN_COPY_DELAY_MS, None),
        ("SPREAD_X3", {"spread_multiplier": 3.0}, FROZEN_COPY_DELAY_MS, None),
        ("DEPTH_50_PERCENT", {"depth_multiplier": 0.5}, FROZEN_COPY_DELAY_MS, None),
        ("DEPTH_25_PERCENT", {"depth_multiplier": 0.25}, FROZEN_COPY_DELAY_MS, None),
    ]
    definitions.extend(
        (
            f"EXTRA_DELAY_{int(extra_ms)}MS",
            {},
            FROZEN_COPY_DELAY_MS + int(extra_ms),
            None,
        )
        for extra_ms in (100, 500, 1_000, 5_000, 30_000, 60_000, 300_000)
    )
    for name, book_stress, delay_ms, stressed_fee_bps in definitions:
        stressed_books = (
            _stress_books(books_by_coin, **book_stress)
            if book_stress
            else books_by_coin
        )
        result = _evaluate_segment(
            metaorders,
            stressed_books,
            segment=f"{segment}_{name.lower()}",
            start_ms=_segment_start_ms(freeze, segment),
            end_ms=_segment_end_ms(freeze, segment),
            params=freeze["parameters"],
            capital_scenario_usd=float(PAPER_EQUITY_USD),
            execution_delay_ms=delay_ms,
            fee_bps=stressed_fee_bps,
        )
        scenarios.append(
            {
                "scenario": name,
                "scope": "DIAGNOSTIC_ONLY",
                "execution_delay_ms": delay_ms,
                "fee_bps": stressed_fee_bps,
                "spread_multiplier": book_stress.get("spread_multiplier", 1.0),
                "depth_multiplier": book_stress.get("depth_multiplier", 1.0),
                "result": result,
            }
        )
    return {
        "schema_version": "hypersmart.copy_vault_stress_diagnostic.v1",
        "segment": str(segment).strip().lower(),
        "scope": "DIAGNOSTIC_ONLY",
        "economic_proof": False,
        "promotion_eligible": False,
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "not_evaluated": {
            "funding_adverse": "UNMEASURABLE_FUNDING_ROWS_NOT_WIRED",
            "bull_bear_sideways_regimes": "UNMEASURABLE_REGIME_LABELS_NOT_PROVEN",
            "missing_leader_data": "NOT_SIMULATED_WITHOUT_MEASURED_OBSERVATION_GAPS",
            "partial_fills": "NOT_MODELED_BY_CURRENT_ALL_OR_NONE_EXECUTOR",
            "missing_venue": "NOT_APPLICABLE_SINGLE_VENUE_COPY_VAULT",
            "instrument_minimums_and_lot_rules": "NOT_EVALUATED",
        },
        "paper_read_only": True,
        "real_execution": False,
    }


def _segment_start_ms(freeze: Mapping[str, Any], segment: str) -> int:
    params = dict(freeze["parameters"])
    bounds = dict(params["bounds"])
    name = str(segment).strip().lower()
    if name == "train":
        return int(bounds["train_start_ms"])
    if name == "validation":
        return int(bounds["validation_start_ms"])
    if name == "oos":
        return int(bounds["oos_start_ms"])
    if name == "forward":
        return int(freeze["frozen_at_ms"]) + 1
    raise ValueError(f"unsupported COPY_V21 segment: {segment!r}")


def _segment_end_ms(freeze: Mapping[str, Any], segment: str) -> int | None:
    bounds = dict(freeze["parameters"]["bounds"])
    name = str(segment).strip().lower()
    if name == "train":
        return int(bounds["train_end_ms"])
    if name == "validation":
        return int(bounds["validation_end_ms"])
    if name == "oos":
        return int(bounds["oos_end_ms"])
    if name == "forward":
        return None
    raise ValueError(f"unsupported COPY_V21 segment: {segment!r}")


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
        complete_utc_day_starts_ms=(input_audit or {}).get("complete_utc_day_starts_ms"),
    )
    if validation["eligible"]:
        oos = _evaluate_segment(
            metaorders,
            books_by_coin,
            segment="oos",
            start_ms=int(bounds["oos_start_ms"]),
            end_ms=int(bounds["oos_end_ms"]),
            params=params,
            complete_utc_day_starts_ms=(input_audit or {}).get("complete_utc_day_starts_ms"),
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
            complete_utc_day_starts_ms=(input_audit or {}).get("complete_utc_day_starts_ms"),
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
    capacity_diagnostic = (
        evaluate_capacity_scenarios(
            metaorders,
            books_by_coin,
            freeze_payload,
            segment="forward",
        )
        if forward.get("heldout_evaluated") is True
        else {
            "schema_version": "hypersmart.copy_vault_capacity_diagnostic.v1",
            "scope": "DIAGNOSTIC_ONLY",
            "economic_proof": False,
            "promotion_eligible": False,
            "status": "NOT_RUN_FORWARD_NOT_EVALUATED",
            "paper_read_only": True,
            "real_execution": False,
        }
    )
    stress_diagnostic = (
        evaluate_stress_matrix(
            metaorders,
            books_by_coin,
            freeze_payload,
            segment="forward",
        )
        if forward.get("eligible") is True
        else {
            "schema_version": "hypersmart.copy_vault_stress_diagnostic.v1",
            "scope": "DIAGNOSTIC_ONLY",
            "economic_proof": False,
            "promotion_eligible": False,
            "status": "NOT_RUN_FORWARD_NOT_ELIGIBLE",
            "paper_read_only": True,
            "real_execution": False,
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "family": "copy_vault",
        "protocol": PROTOCOL,
        "reference_feature_policy": "LATEST_CAUSAL_RECEIVED_BOOK_AT_OR_BEFORE_SIGNAL_V1",
        "objective_net_usd_per_day": REFERENCE_DAILY_OBJECTIVE_USD,
        "objective_is_informational_reference_only": True,
        "objective_status": _reference_objective_status(validation, oos, forward),
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
        "capacity_diagnostic": capacity_diagnostic,
        "stress_diagnostic": stress_diagnostic,
        "carry_pnl_usd": 0.0,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "CAPACITY_SCENARIOS_USD",
    "PROTOCOL",
    "SCHEMA_VERSION",
    "evaluate_capacity_scenarios",
    "evaluate_frozen_v21",
    "evaluate_frozen_v21_segment",
    "evaluate_stress_matrix",
]
