"""Cross-Venue v4 TRAIN-only: executable entry and executable exits.

V3 proved that a mid-price convergence is not an executable exit. V4 keeps
the same causal leader-impulse event, but freezes a finite family of exit
policies over four-fill net PnL. It is intentionally TRAIN-only and cannot
read, label or certify validation/OOS/forward observations.

PAPER/READ-ONLY. No exchange or order client is imported by this module.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting import cross_venue_v3_train as v3
from hl_observer.backtesting.cross_venue_certified import BBO_SOURCE_MODE, SOURCE_MODE
from hl_observer.backtesting.train_statistics import stable_hash, summarize_train_rows
from hl_observer.economics.assumptions import EconomicRunMode
from hl_observer.economics.families import FamilyEconomicContract

SCHEMA_VERSION = "hypersmart.cross_venue_v4_train.v1"
MECHANISM = "cross_venue_v4_executable_net_exit"

# Fixed before any held-out evaluation. The entry floor is derived from the
# four-fill fee contract plus this predeclared adverse-selection reserve.
LEADER_THRESHOLD_BPS = 8.0
ADVERSE_SELECTION_RESERVE_BPS = 12.0
MAX_HOLD_MS = 30_000
MAX_EXIT_DELAY_MS = 1_000
TAKE_PROFIT_NET_BPS = (2.0, 4.0, 8.0, 12.0)
STOP_LOSS_NET_BPS = (8.0, 12.0, 20.0, 30.0)

MIN_TRAIN_TRADES = 8
MIN_DISTINCT_DAYS = 3
MAX_TOP_POSITIVE_SHARE = 0.60
FAMILY_ALPHA = 0.05


def minimum_entry_executable_edge_bps(
    mode: EconomicRunMode | str = EconomicRunMode.EXPLORATORY,
) -> float:
    return float(
        v3.economic_contract(mode)
        .registry.get("cross_venue.minimum_entry_edge_bps")
        .value
    )


MIN_ENTRY_EXECUTABLE_EDGE_BPS = minimum_entry_executable_edge_bps()


def _policy_trade_id(
    *,
    coin: str,
    raw_trade_id: str,
    take_profit_net_bps: float,
    stop_loss_net_bps: float,
) -> str:
    material = (
        f"{MECHANISM}|{coin}|{raw_trade_id}|"
        f"{take_profit_net_bps}|{stop_loss_net_bps}"
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _build_train_paths(
    series: Mapping[str, Sequence[Sequence[Any]]],
    depth: Mapping[str, Sequence[tuple[float, float]]],
    *,
    train_end_ms: float,
    economic: FamilyEconomicContract | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Build causal entry-to-expiry paths once for the finite policy family."""

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
            leader_threshold_bps=LEADER_THRESHOLD_BPS,
            train_end_ms=float(train_end_ms),
        )
        for impulse in impulses:
            entry_match = v3._first_at_or_after(
                rows,
                float(impulse["detect_ts_ms"]) + latency_ms,
                max_delay_ms=v3.MAX_ENTRY_DELAY_MS,
            )
            if entry_match is None:
                diagnostics["MISSING_LATENCY_DELAYED_ENTRY"] += 1
                continue
            entry_index, entry = entry_match
            if float(entry[0]) > float(train_end_ms):
                diagnostics["ENTRY_OUTSIDE_TRAIN"] += 1
                continue
            entry_basis = v3._basis_bps(entry)
            if entry_basis is None or int(impulse["direction"]) * float(entry_basis) <= 0:
                diagnostics["BASIS_REVERSED_BEFORE_ENTRY"] += 1
                continue
            entry_capacity = v3._capacity_at(
                coin_depth,
                float(entry[0]),
                max_age_ms=max_book_age_ms,
            )
            if entry_capacity is None or entry_capacity[0] < notional_usd:
                diagnostics["ENTRY_CAPACITY_REJECTED"] += 1
                continue
            executable_entry_edge = v3._entry_executable_edge_bps(
                entry,
                direction=int(impulse["direction"]),
            )
            if (
                executable_entry_edge is None
                or executable_entry_edge < minimum_entry_edge
            ):
                diagnostics["ENTRY_EDGE_RESERVE_REJECTED"] += 1
                continue

            cycles: list[dict[str, Any]] = []
            previous_ts = float(entry[0])
            expiry_observed = False
            path_invalidated = False
            for candidate in rows[entry_index + 1 :]:
                timestamp = float(candidate[0])
                if timestamp > float(train_end_ms):
                    break
                if timestamp - previous_ts > max_book_age_ms:
                    diagnostics["OBSERVATION_GAP_INVALIDATED"] += 1
                    path_invalidated = True
                    break
                previous_ts = timestamp
                elapsed_ms = timestamp - float(entry[0])
                if elapsed_ms > MAX_HOLD_MS + MAX_EXIT_DELAY_MS:
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
                    }
                )
                cycles.append(cycle)
                if elapsed_ms >= MAX_HOLD_MS:
                    expiry_observed = True
                    break
            if path_invalidated:
                continue
            if not cycles or not expiry_observed:
                diagnostics["NO_EXECUTABLE_TIME_STOP"] += 1
                continue
            path_material = (
                f"{coin}|{impulse['detect_ts_ms']}|{entry[0]}|"
                f"{impulse['direction']}|{MECHANISM}"
            )
            paths.append(
                {
                    "path_id": hashlib.sha256(path_material.encode("utf-8")).hexdigest(),
                    "coin": coin,
                    "leader_venue": impulse["leader_venue"],
                    "direction": int(impulse["direction"]),
                    "entry_executable_edge_bps": float(executable_entry_edge),
                    "minimum_entry_executable_edge_bps": minimum_entry_edge,
                    "assumption_snapshot_hash": contract.registry.snapshot_hash(),
                    "cycles": cycles,
                }
            )
            diagnostics["EXECUTABLE_ENTRY_PATH"] += 1
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
                "max_hold_ms": MAX_HOLD_MS,
                "minimum_entry_executable_edge_bps": float(
                    path.get("minimum_entry_executable_edge_bps")
                    or MIN_ENTRY_EXECUTABLE_EDGE_BPS
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


def replay_policy_train(
    series: Mapping[str, Sequence[Sequence[Any]]],
    depth: Mapping[str, Sequence[tuple[float, float]]],
    *,
    take_profit_net_bps: float,
    stop_loss_net_bps: float,
    train_end_ms: float,
    economic_mode: EconomicRunMode | str = EconomicRunMode.EXPLORATORY,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Replay one policy over TRAIN rows; exposed for deterministic tests."""

    contract = v3.economic_contract(economic_mode)
    paths, path_diagnostics = _build_train_paths(
        series,
        depth,
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
    total = 0.0
    for row in trades:
        total += -float(row.get("gross_pnl_usd") or 0.0) - float(row.get("fees_usd") or 0.0)
    return total


def explore_cross_venue_v4_train(
    series: Mapping[str, Sequence[Sequence[Any]]],
    depth: Mapping[str, Sequence[tuple[float, float]]],
    *,
    source_mode: str,
    economic_mode: EconomicRunMode | str = EconomicRunMode.EXPLORATORY,
) -> dict[str, Any]:
    """Select only from TRAIN, with a multiplicity-adjusted finite grid."""

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
    paths, path_diagnostics = _build_train_paths(
        series,
        depth,
        train_end_ms=train_end_ms,
        economic=contract,
    )
    grid = [
        (take_profit, stop_loss)
        for take_profit in TAKE_PROFIT_NET_BPS
        for stop_loss in STOP_LOSS_NET_BPS
    ]
    trial_count = len(v3.PREDECLARED_COINS) * len(grid)
    variants: list[dict[str, Any]] = []
    for take_profit, stop_loss in grid:
        trades, diagnostics = _settle_policy(
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
                "take_profit_net_bps": take_profit,
                "stop_loss_net_bps": stop_loss,
                "statistics": statistics,
                "placebo_net_pnl_usd": placebo_net,
                "diagnostics": diagnostics,
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
            "leader_threshold_bps": LEADER_THRESHOLD_BPS,
            "minimum_entry_executable_edge_bps": minimum_entry_edge,
            "take_profit_net_bps": selected["take_profit_net_bps"],
            "stop_loss_net_bps": selected["stop_loss_net_bps"],
            "max_hold_ms": MAX_HOLD_MS,
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
        "fixed_grid": {
            "leader_threshold_bps": LEADER_THRESHOLD_BPS,
            "minimum_entry_executable_edge_bps": minimum_entry_edge,
            "take_profit_net_bps": list(TAKE_PROFIT_NET_BPS),
            "stop_loss_net_bps": list(STOP_LOSS_NET_BPS),
            "max_hold_ms": MAX_HOLD_MS,
            "predeclared_coins": list(v3.PREDECLARED_COINS),
            "trial_count": trial_count,
        },
        "cost_contract": {
            "fee_bps_hyperliquid_per_fill": fee_hl,
            "fee_bps_binance_per_fill": fee_bin,
            "fees_round_trip_bps": fees_round_trip,
            "fee_fill_count": 4,
            "spread_embedded_in_executable_prices": True,
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
    "ADVERSE_SELECTION_RESERVE_BPS",
    "MECHANISM",
    "MIN_ENTRY_EXECUTABLE_EDGE_BPS",
    "SCHEMA_VERSION",
    "explore_cross_venue_v4_train",
    "minimum_entry_executable_edge_bps",
    "replay_policy_train",
]
