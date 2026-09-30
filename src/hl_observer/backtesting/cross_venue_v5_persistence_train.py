"""Cross-Venue v5 TRAIN-only: persistent executable dislocations.

V4 accepted an executable spread from one latency-delayed snapshot. V5 requires
that the same executable direction and the 30 bps reserve survive consecutive
certified atomic observations before entering on the last confirmation.

The confirmation contracts were fixed from feed cadence only, before replaying
their outcomes: two observations within one second or three within two seconds.
The module remains PAPER/READ-ONLY and cannot inspect held-out observations.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting import cross_venue_v3_train as v3
from hl_observer.backtesting import cross_venue_v4_train as v4
from hl_observer.backtesting.cross_venue_certified import BBO_SOURCE_MODE, SOURCE_MODE
from hl_observer.backtesting.train_statistics import stable_hash, summarize_train_rows
from hl_observer.economics.assumptions import EconomicRunMode
from hl_observer.economics.families import FamilyEconomicContract

SCHEMA_VERSION = "hypersmart.cross_venue_v5_persistence_train.v1"
MECHANISM = "cross_venue_v5_persistent_executable_dislocation"

# Fixed from the measured atomic-feed cadence without reading future PnL.
# Median inter-arrival was about 0.4 s; these two contracts require observable
# persistence while retaining enough candidates for a falsifiable TRAIN replay.
CONFIRMATION_POLICIES = ((2, 1_000), (3, 2_000))

MIN_TRAIN_TRADES = 8
MIN_DISTINCT_DAYS = 3
MAX_TOP_POSITIVE_SHARE = 0.60
FAMILY_ALPHA = 0.05


def _policy_trade_id(
    *,
    coin: str,
    raw_trade_id: str,
    confirmation_count: int,
    max_confirmation_window_ms: int,
    take_profit_net_bps: float,
    stop_loss_net_bps: float,
) -> str:
    material = "|".join(
        (
            MECHANISM,
            coin,
            raw_trade_id,
            str(int(confirmation_count)),
            str(int(max_confirmation_window_ms)),
            str(float(take_profit_net_bps)),
            str(float(stop_loss_net_bps)),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _confirmed_entry(
    rows: Sequence[Sequence[Any]],
    depth: Sequence[tuple[float, float]],
    *,
    start_index: int,
    direction: int,
    confirmation_count: int,
    max_confirmation_window_ms: int,
    train_end_ms: float,
    diagnostics: dict[str, int],
    minimum_entry_edge_bps: float,
    notional_usd: float,
    max_book_age_ms: float,
) -> tuple[int, Sequence[Any], tuple[float, float], int] | None:
    """Return the last strictly causal confirmation, never the first snapshot."""

    if confirmation_count < 2 or start_index >= len(rows):
        diagnostics["INVALID_CONFIRMATION_CONTRACT"] += 1
        return None
    first_ts = float(rows[start_index][0])
    previous_counted_ts: float | None = None
    observed = 0
    for index in range(start_index, len(rows)):
        row = rows[index]
        timestamp = float(row[0])
        if timestamp > float(train_end_ms):
            diagnostics["CONFIRMATION_OUTSIDE_TRAIN"] += 1
            return None
        if timestamp - first_ts > int(max_confirmation_window_ms):
            diagnostics["CONFIRMATION_WINDOW_EXPIRED"] += 1
            return None
        if previous_counted_ts is not None:
            gap_ms = timestamp - previous_counted_ts
            if gap_ms < 0:
                diagnostics["CONFIRMATION_NON_MONOTONIC"] += 1
                return None
            if gap_ms > float(max_book_age_ms):
                diagnostics["CONFIRMATION_GAP_INVALIDATED"] += 1
                return None

        basis = v3._basis_bps(row)
        if basis is None or int(direction) * float(basis) <= 0:
            diagnostics["CONFIRMATION_BASIS_REVERSED"] += 1
            return None
        executable_edge = v3._entry_executable_edge_bps(row, direction=int(direction))
        if executable_edge is None or executable_edge < float(minimum_entry_edge_bps):
            diagnostics["CONFIRMATION_EDGE_LOST"] += 1
            return None
        capacity = v3._capacity_at(depth, timestamp, max_age_ms=float(max_book_age_ms))
        if capacity is None or capacity[0] < float(notional_usd):
            diagnostics["CONFIRMATION_CAPACITY_REJECTED"] += 1
            return None

        # Multiple state changes may share a wall-clock millisecond. They must
        # remain valid, but do not constitute independent persistence evidence.
        if previous_counted_ts is not None and timestamp == previous_counted_ts:
            diagnostics["SAME_TIMESTAMP_CONFIRMATION_NOT_COUNTED"] += 1
            continue
        observed += 1
        previous_counted_ts = timestamp
        if observed >= int(confirmation_count):
            return index, row, capacity, int(timestamp - first_ts)

    diagnostics["CONFIRMATION_INCOMPLETE"] += 1
    return None


def _build_train_paths(
    series: Mapping[str, Sequence[Sequence[Any]]],
    depth: Mapping[str, Sequence[tuple[float, float]]],
    *,
    confirmation_count: int,
    max_confirmation_window_ms: int,
    train_end_ms: float,
    economic: FamilyEconomicContract | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    contract = economic or v3.economic_contract()
    contract.registry.assert_consistent()
    minimum_entry_edge = float(
        contract.registry.get("cross_venue.minimum_entry_edge_bps").value
    )
    fees_round_trip = float(
        contract.registry.get("cross_venue.round_trip_fee_bps").value
    )
    notional_usd = float(contract.registry.get("cross_venue.paper_notional_usd").value)
    latency_ms = float(contract.registry.get("cross_venue.entry_latency_ms").value)
    max_book_age_ms = float(contract.registry.get("cross_venue.max_book_age_ms").value)
    paths: list[dict[str, Any]] = []
    diagnostics: dict[str, int] = defaultdict(int)
    for coin in v3.PREDECLARED_COINS:
        rows = sorted(list(series.get(coin, ())), key=lambda row: float(row[0]))
        if len(rows) < 2:
            continue
        coin_depth = sorted(list(depth.get(coin, ())))
        impulses = v3._detect_impulses(
            rows,
            leader_threshold_bps=v4.LEADER_THRESHOLD_BPS,
            train_end_ms=float(train_end_ms),
        )
        for impulse in impulses:
            delayed = v3._first_at_or_after(
                rows,
                float(impulse["detect_ts_ms"]) + latency_ms,
                max_delay_ms=v3.MAX_ENTRY_DELAY_MS,
            )
            if delayed is None:
                diagnostics["MISSING_LATENCY_DELAYED_ENTRY"] += 1
                continue
            delayed_index, _ = delayed
            confirmed = _confirmed_entry(
                rows,
                coin_depth,
                start_index=delayed_index,
                direction=int(impulse["direction"]),
                confirmation_count=int(confirmation_count),
                max_confirmation_window_ms=int(max_confirmation_window_ms),
                train_end_ms=float(train_end_ms),
                diagnostics=diagnostics,
                minimum_entry_edge_bps=minimum_entry_edge,
                notional_usd=notional_usd,
                max_book_age_ms=max_book_age_ms,
            )
            if confirmed is None:
                continue
            entry_index, entry, entry_capacity, confirmation_duration_ms = confirmed
            entry_basis = v3._basis_bps(entry)
            executable_entry_edge = v3._entry_executable_edge_bps(
                entry,
                direction=int(impulse["direction"]),
            )
            if entry_basis is None or executable_entry_edge is None:
                diagnostics["CONFIRMED_ENTRY_INVALID"] += 1
                continue

            cycles: list[dict[str, Any]] = []
            previous_ts = float(entry[0])
            expiry_observed = False
            path_invalidated = False
            for candidate in rows[entry_index + 1 :]:
                timestamp = float(candidate[0])
                if timestamp > float(train_end_ms):
                    break
                if timestamp <= previous_ts:
                    diagnostics["NON_CAUSAL_EXIT_OBSERVATION_SKIPPED"] += 1
                    continue
                if timestamp - previous_ts > max_book_age_ms:
                    diagnostics["OBSERVATION_GAP_INVALIDATED"] += 1
                    path_invalidated = True
                    break
                previous_ts = timestamp
                elapsed_ms = timestamp - float(entry[0])
                if elapsed_ms > v4.MAX_HOLD_MS + v4.MAX_EXIT_DELAY_MS:
                    break
                exit_capacity = v3._capacity_at(
                    coin_depth,
                    timestamp,
                    max_age_ms=max_book_age_ms,
                )
                if exit_capacity is None or exit_capacity[0] < notional_usd:
                    diagnostics["EXIT_CAPACITY_SKIPPED"] += 1
                    continue
                cycle = v3._executable_cycle(
                    entry,
                    candidate,
                    direction=int(impulse["direction"]),
                    notional_usd=notional_usd,
                    fees_bps=fees_round_trip,
                    entry_capacity=entry_capacity[0],
                    exit_capacity=exit_capacity[0],
                    detect_ts_ms=float(impulse["detect_ts_ms"]),
                )
                if cycle is None or cycle.get("LIQUIDATABLE_NET") is not True:
                    diagnostics["ECONOMIC_CYCLE_REJECTED"] += 1
                    continue
                cycle.update(
                    {
                        "coin": coin,
                        "leader_venue": impulse["leader_venue"],
                        "entry_executable_edge_bps": float(executable_entry_edge),
                        "basis_in_bps": float(entry_basis),
                        "basis_out_bps": float(v3._basis_bps(candidate) or 0.0),
                        "depth_freshness_ms": max(entry_capacity[1], exit_capacity[1]),
                        "confirmation_count": int(confirmation_count),
                        "max_confirmation_window_ms": int(max_confirmation_window_ms),
                        "confirmation_duration_ms": int(confirmation_duration_ms),
                        "minimum_entry_executable_edge_bps": minimum_entry_edge,
                        "assumption_snapshot_hash": contract.registry.snapshot_hash(),
                    }
                )
                cycles.append(cycle)
                if elapsed_ms >= v4.MAX_HOLD_MS:
                    expiry_observed = True
                    break
            if path_invalidated:
                continue
            if not cycles or not expiry_observed:
                diagnostics["NO_EXECUTABLE_TIME_STOP"] += 1
                continue
            path_material = "|".join(
                (
                    coin,
                    str(impulse["detect_ts_ms"]),
                    str(entry[0]),
                    str(impulse["direction"]),
                    str(int(confirmation_count)),
                    str(int(max_confirmation_window_ms)),
                    MECHANISM,
                )
            )
            paths.append(
                {
                    "path_id": hashlib.sha256(path_material.encode("utf-8")).hexdigest(),
                    "coin": coin,
                    "leader_venue": impulse["leader_venue"],
                    "direction": int(impulse["direction"]),
                    "entry_executable_edge_bps": float(executable_entry_edge),
                    "confirmation_count": int(confirmation_count),
                    "max_confirmation_window_ms": int(max_confirmation_window_ms),
                    "confirmation_duration_ms": int(confirmation_duration_ms),
                    "minimum_entry_executable_edge_bps": minimum_entry_edge,
                    "assumption_snapshot_hash": contract.registry.snapshot_hash(),
                    "cycles": cycles,
                }
            )
            diagnostics["PERSISTENT_EXECUTABLE_ENTRY_PATH"] += 1
    paths.sort(key=lambda row: (int(row["cycles"][0]["entry_ts_ms"]), str(row["coin"])))
    return paths, dict(diagnostics)


def _settle_policy(
    paths: Sequence[Mapping[str, Any]],
    *,
    take_profit_net_bps: float,
    stop_loss_net_bps: float,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    trades: list[dict[str, Any]] = []
    diagnostics: dict[str, int] = defaultdict(int)
    seen_ids: set[str] = set()
    for path in paths:
        cycles = list(path.get("cycles") or ())
        if not cycles:
            continue
        selected = cycles[-1]
        exit_reason = "TIME_STOP"
        for cycle in cycles:
            net_bps = float(cycle.get("net_bps") or 0.0)
            if net_bps >= float(take_profit_net_bps):
                selected = cycle
                exit_reason = "TAKE_PROFIT_NET"
                break
            if net_bps <= -float(stop_loss_net_bps):
                selected = cycle
                exit_reason = "STOP_LOSS_NET"
                break
        trade = dict(selected)
        raw_trade_id = str(trade.get("trade_id") or "")
        trade["cycle_trade_id"] = raw_trade_id
        trade["trade_id"] = _policy_trade_id(
            coin=str(path["coin"]),
            raw_trade_id=raw_trade_id,
            confirmation_count=int(path["confirmation_count"]),
            max_confirmation_window_ms=int(path["max_confirmation_window_ms"]),
            take_profit_net_bps=float(take_profit_net_bps),
            stop_loss_net_bps=float(stop_loss_net_bps),
        )
        if trade["trade_id"] in seen_ids:
            diagnostics["DUPLICATE_POLICY_TRADE_ID"] += 1
            continue
        seen_ids.add(trade["trade_id"])
        trade.update(
            {
                "mechanism": MECHANISM,
                "exit_reason": exit_reason,
                "take_profit_net_bps": float(take_profit_net_bps),
                "stop_loss_net_bps": float(stop_loss_net_bps),
                "max_hold_ms": v4.MAX_HOLD_MS,
                "minimum_entry_executable_edge_bps": float(
                    path.get("minimum_entry_executable_edge_bps")
                    or v4.MIN_ENTRY_EXECUTABLE_EDGE_BPS
                ),
                "assumption_snapshot_hash": path.get("assumption_snapshot_hash"),
                "paper_read_only": True,
                "real_execution": False,
            }
        )
        trades.append(trade)
        diagnostics[exit_reason] += 1
    trades.sort(key=lambda row: (int(row["entry_ts_ms"]), str(row["coin"])))
    return trades, dict(diagnostics)


def replay_persistence_policy_train(
    series: Mapping[str, Sequence[Sequence[Any]]],
    depth: Mapping[str, Sequence[tuple[float, float]]],
    *,
    confirmation_count: int,
    max_confirmation_window_ms: int,
    take_profit_net_bps: float,
    stop_loss_net_bps: float,
    train_end_ms: float,
    economic_mode: EconomicRunMode | str = EconomicRunMode.EXPLORATORY,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    contract = v3.economic_contract(economic_mode)
    paths, path_diagnostics = _build_train_paths(
        series,
        depth,
        confirmation_count=int(confirmation_count),
        max_confirmation_window_ms=int(max_confirmation_window_ms),
        train_end_ms=float(train_end_ms),
        economic=contract,
    )
    trades, policy_diagnostics = _settle_policy(
        paths,
        take_profit_net_bps=float(take_profit_net_bps),
        stop_loss_net_bps=float(stop_loss_net_bps),
    )
    combined = defaultdict(int, path_diagnostics)
    for reason, count in policy_diagnostics.items():
        combined[reason] += int(count)
    return trades, dict(combined)


def _placebo_net(trades: Sequence[Mapping[str, Any]]) -> float:
    return sum(
        -float(row.get("gross_pnl_usd") or 0.0) - float(row.get("fees_usd") or 0.0)
        for row in trades
    )


def explore_cross_venue_v5_train(
    series: Mapping[str, Sequence[Sequence[Any]]],
    depth: Mapping[str, Sequence[tuple[float, float]]],
    *,
    source_mode: str,
    economic_mode: EconomicRunMode | str = EconomicRunMode.EXPLORATORY,
) -> dict[str, Any]:
    contract = v3.economic_contract(economic_mode)
    economic_receipt = contract.receipt()
    minimum_entry_edge = float(
        contract.registry.get("cross_venue.minimum_entry_edge_bps").value
    )
    fees_round_trip = float(
        contract.registry.get("cross_venue.round_trip_fee_bps").value
    )
    fee_hl = float(contract.registry.get("fee.taker.hyperliquid.bps").value)
    fee_bin = float(contract.registry.get("fee.taker.binance.bps").value)
    latency_ms = float(contract.registry.get("cross_venue.entry_latency_ms").value)
    notional_usd = float(contract.registry.get("cross_venue.paper_notional_usd").value)
    all_ts = sorted(
        float(row[0])
        for coin in v3.PREDECLARED_COINS
        for row in series.get(coin, ())
        if row and float(row[0]) > 0
    )
    if not all_ts or source_mode not in {SOURCE_MODE, BBO_SOURCE_MODE}:
        return {
            "schema_version": SCHEMA_VERSION,
            "mechanism": MECHANISM,
            "status": "MORE_DATA_CERTIFIED_ATOMIC_BOOK_REQUIRED",
            "selection_eligible": False,
            "physical_freeze_allowed": False,
            "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
            "heldout_evaluated": False,
            "source_mode": source_mode,
            "economic_contract": economic_receipt,
            "paper_read_only": True,
            "real_execution": False,
        }

    start_ms, end_ms = all_ts[0], all_ts[-1]
    train_end_ms = start_ms + (end_ms - start_ms) * v3.TRAIN_FRACTION
    exit_grid = [
        (take_profit, stop_loss)
        for take_profit in v4.TAKE_PROFIT_NET_BPS
        for stop_loss in v4.STOP_LOSS_NET_BPS
    ]
    trial_count = len(v3.PREDECLARED_COINS) * len(CONFIRMATION_POLICIES) * len(exit_grid)
    variants: list[dict[str, Any]] = []
    path_diagnostics: dict[str, dict[str, int]] = {}
    for confirmation_count, max_window_ms in CONFIRMATION_POLICIES:
        paths, diagnostics = _build_train_paths(
            series,
            depth,
            confirmation_count=confirmation_count,
            max_confirmation_window_ms=max_window_ms,
            train_end_ms=train_end_ms,
            economic=contract,
        )
        path_diagnostics[f"{confirmation_count}_within_{max_window_ms}ms"] = diagnostics
        for take_profit, stop_loss in exit_grid:
            trades, policy_diagnostics = _settle_policy(
                paths,
                take_profit_net_bps=take_profit,
                stop_loss_net_bps=stop_loss,
            )
            statistics = summarize_train_rows(
                trades,
                value_key="net_pnl_usd",
                timestamp_key="entry_ts_ms",
                trial_count=trial_count,
                family_alpha=FAMILY_ALPHA,
            )
            net = float(statistics.get("net_pnl_usd") or 0.0)
            profit_factor = statistics.get("profit_factor")
            total_lcb = statistics.get("total_lcb_usd")
            placebo_net = _placebo_net(trades)
            eligible = bool(
                len(trades) >= MIN_TRAIN_TRADES
                and int(statistics.get("distinct_days") or 0) >= MIN_DISTINCT_DAYS
                and net > 0.0
                and profit_factor is not None
                and float(profit_factor) > 1.0
                and total_lcb is not None
                and float(total_lcb) > 0.0
                and float(statistics.get("top_positive_trade_share") or 1.0)
                <= MAX_TOP_POSITIVE_SHARE
                and net > placebo_net + 1e-12
            )
            variants.append(
                {
                    "confirmation_count": confirmation_count,
                    "max_confirmation_window_ms": max_window_ms,
                    "take_profit_net_bps": take_profit,
                    "stop_loss_net_bps": stop_loss,
                    "statistics": statistics,
                    "placebo_net_pnl_usd": placebo_net,
                    "diagnostics": policy_diagnostics,
                    "eligible": eligible,
                }
            )

    eligible_rows = [row for row in variants if row["eligible"]]
    selected = max(
        eligible_rows,
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
            "leader_threshold_bps": v4.LEADER_THRESHOLD_BPS,
            "minimum_entry_executable_edge_bps": minimum_entry_edge,
            "confirmation_count": selected["confirmation_count"],
            "max_confirmation_window_ms": selected["max_confirmation_window_ms"],
            "take_profit_net_bps": selected["take_profit_net_bps"],
            "stop_loss_net_bps": selected["stop_loss_net_bps"],
            "max_hold_ms": v4.MAX_HOLD_MS,
            "latency_ms": latency_ms,
            "notional_usd": notional_usd,
            "fees_round_trip_bps": fees_round_trip,
            "fee_fill_count": 4,
            "spread_embedded_in_executable_prices": True,
            "predeclared_coins": list(v3.PREDECLARED_COINS),
            "source_mode": source_mode,
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
        "source_mode": source_mode,
        "train_bounds": {"start_ms": start_ms, "end_ms": train_end_ms, "full_end_ms": end_ms},
        "predeclaration_basis": {
            "outcomes_read_before_confirmation_contract": False,
            "measured_median_interarrival_ms_approx": 400,
            "measured_confirmation_candidates": {
                "one_snapshot": 110,
                "two_within_2s": 94,
                "three_within_2s": 80,
            },
        },
        "fixed_grid": {
            "leader_threshold_bps": v4.LEADER_THRESHOLD_BPS,
            "minimum_entry_executable_edge_bps": minimum_entry_edge,
            "confirmation_policies": [
                {"count": count, "max_window_ms": window}
                for count, window in CONFIRMATION_POLICIES
            ],
            "take_profit_net_bps": list(v4.TAKE_PROFIT_NET_BPS),
            "stop_loss_net_bps": list(v4.STOP_LOSS_NET_BPS),
            "max_hold_ms": v4.MAX_HOLD_MS,
            "predeclared_coins": list(v3.PREDECLARED_COINS),
            "trial_count": trial_count,
        },
        "cost_contract": {
            "fee_bps_hyperliquid_per_fill": fee_hl,
            "fee_bps_binance_per_fill": fee_bin,
            "fees_round_trip_bps": fees_round_trip,
            "fee_fill_count": 4,
            "spread_embedded_in_executable_prices": True,
            "confirmation_enters_on_last_observation": True,
            "exit_thresholds_use_liquidatable_net_bps": True,
        },
        "economic_contract": economic_receipt,
        "path_diagnostics": path_diagnostics,
        "selected": selected,
        "diagnostic_best_train_variant": diagnostic_best,
        "freeze_candidate": freeze_candidate,
        "freeze_candidate_sha256": stable_hash(freeze_candidate) if freeze_candidate else None,
        "variants": variants,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "CONFIRMATION_POLICIES",
    "MECHANISM",
    "SCHEMA_VERSION",
    "explore_cross_venue_v5_train",
    "replay_persistence_policy_train",
]
