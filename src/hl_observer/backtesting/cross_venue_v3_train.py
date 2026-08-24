"""Materially new Cross-Venue v3 TRAIN-only mechanism.

V2 traded a static basis threshold.  V3 instead requires a causal leader impulse:
one venue moves sharply while the other remains temporarily quiet, the observed
HL/Binance basis widens in consequence, and only then may a latency-delayed
four-side paper cycle be considered.  Selection sees only the first 60% of the
recorded certified atomic chronology and uses a fixed grid plus a Bonferroni
lower confidence bound.

This is pre-freeze research only.  It cannot certify Cross-Venue or access
validation/OOS/forward.  PAPER/READ-ONLY; no exchange client exists here.
"""
from __future__ import annotations

import bisect
import hashlib
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.backtesting.cross_venue_certified import BBO_SOURCE_MODE, SOURCE_MODE
from hl_observer.backtesting.train_statistics import stable_hash, summarize_train_rows

SCHEMA_VERSION = "hypersmart.cross_venue_v3_train.v1"
MECHANISM = "cross_venue_v3_leader_impulse_basis_reversion"
PREDECLARED_COINS = ("BTC", "ETH", "SOL", "AVAX", "INJ", "DASH", "NEO", "LINK", "AAVE", "ONDO")
LEADER_THRESHOLDS_BPS = (8.0, 12.0)
MAX_HOLDS_MS = (10_000, 30_000)
LOOKBACK_MS = 2_000
LAGGER_MAX_MOVE_BPS = 3.0
MIN_BASIS_WIDENING_BPS = 5.0
CONVERGENCE_RATIO = 0.50
LATENCY_MS = 400
MAX_ENTRY_DELAY_MS = 1_000
MAX_OBSERVATION_GAP_MS = 3_000
FEES_ROUND_TRIP_BPS = 16.0
NOTIONAL_USD = 15.0
TRAIN_FRACTION = 0.60
MIN_TRAIN_TRADES = 8
MIN_DISTINCT_DAYS = 3
MAX_TOP_POSITIVE_SHARE = 0.60
FAMILY_ALPHA = 0.05


def _mid(bid: float, ask: float) -> float:
    return 0.5 * (float(bid) + float(ask))


def _basis_bps(row: Sequence[Any]) -> float | None:
    try:
        hl_mid = _mid(float(row[2]), float(row[3]))
        bin_mid = _mid(float(row[4]), float(row[5]))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    fair = 0.5 * (hl_mid + bin_mid)
    return (hl_mid - bin_mid) / fair * 10_000.0 if fair > 0 else None


def _move_bps(before: float, after: float) -> float | None:
    if before <= 0 or after <= 0:
        return None
    return (after - before) / before * 10_000.0


def _capacity_at(
    rows: Sequence[tuple[float, float]], timestamp_ms: float, *, max_age_ms: float = 3_000.0
) -> tuple[float, float] | None:
    if not rows:
        return None
    index = bisect.bisect_right(rows, (float(timestamp_ms), float("inf"))) - 1
    if index < 0:
        return None
    observed, capacity = rows[index]
    age = float(timestamp_ms) - float(observed)
    if age < 0 or age > float(max_age_ms) or float(capacity) <= 0:
        return None
    return float(capacity), age


def _first_at_or_after(
    rows: Sequence[Sequence[Any]], target_ms: float, *, max_delay_ms: float
) -> tuple[int, Sequence[Any]] | None:
    timestamps = [float(row[0]) for row in rows]
    index = bisect.bisect_left(timestamps, float(target_ms))
    if index >= len(rows):
        return None
    delay = float(rows[index][0]) - float(target_ms)
    return (index, rows[index]) if 0.0 <= delay <= float(max_delay_ms) else None


def _executable_cycle(
    entry: Sequence[Any],
    exit_: Sequence[Any],
    *,
    direction: int,
    notional_usd: float,
    fees_bps: float,
    entry_capacity: float,
    exit_capacity: float,
    detect_ts_ms: float,
) -> dict[str, Any] | None:
    """Settle four top-of-book fills; certified top capacity must cover all legs."""

    if min(float(entry_capacity), float(exit_capacity)) + 1e-12 < float(notional_usd):
        return None
    hb_i, ha_i, bb_i, ba_i = map(float, entry[2:6])
    hb_o, ha_o, bb_o, ba_o = map(float, exit_[2:6])
    if min(hb_i, ha_i, bb_i, ba_i, hb_o, ha_o, bb_o, ba_o) <= 0:
        return None
    if direction > 0:  # HL expensive: short HL, long BIN; reverse at exit.
        pnl_hl = (hb_i - ha_o) / hb_i
        pnl_bin = (bb_o - ba_i) / ba_i
        entry_fills = {"hl": hb_i, "bin": ba_i}
        exit_fills = {"hl": ha_o, "bin": bb_o}
    else:
        pnl_hl = (hb_o - ha_i) / ha_i
        pnl_bin = (bb_i - ba_o) / bb_i
        entry_fills = {"hl": ha_i, "bin": bb_i}
        exit_fills = {"hl": hb_o, "bin": ba_o}
    gross_bps = (pnl_hl + pnl_bin) * 10_000.0
    net_bps = gross_bps - float(fees_bps)
    gross_usd = float(notional_usd) * gross_bps / 10_000.0
    fees_usd = float(notional_usd) * float(fees_bps) / 10_000.0
    net_usd = float(notional_usd) * net_bps / 10_000.0
    identity = (
        f"{entry[0]}|{exit_[0]}|{direction}|{notional_usd}|{MECHANISM}"
    )
    reconciled = math.isclose(gross_usd - fees_usd, net_usd, abs_tol=1e-9)
    return {
        "trade_id": hashlib.sha256(identity.encode("utf-8")).hexdigest(),
        "detect_ts_ms": int(detect_ts_ms),
        "entry_ts_ms": int(float(entry[0])),
        "exit_ts_ms": int(float(exit_[0])),
        "direction": int(direction),
        "notional_usd": float(notional_usd),
        "entry_fills": entry_fills,
        "exit_fills": exit_fills,
        "entry_capacity_usd": float(entry_capacity),
        "exit_capacity_usd": float(exit_capacity),
        "gross_pnl_usd": gross_usd,
        "fees_usd": fees_usd,
        "spread_cost_usd": 0.0,
        "slippage_cost_usd": 0.0,
        "latency_cost_usd": 0.0,
        "net_pnl_usd": net_usd,
        "gross_bps": gross_bps,
        "net_bps": net_bps,
        "four_fills_complete": True,
        "two_leg": True,
        "LIQUIDATABLE_NET": reconciled,
        "economic_reconciliation_ok": reconciled,
        "latency_embedded_in_delayed_entry": True,
        "paper_read_only": True,
        "real_execution": False,
    }


def _detect_impulses(
    rows: Sequence[Sequence[Any]],
    *,
    leader_threshold_bps: float,
    train_end_ms: float,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    previous_index = 0
    last_detect_ms = -10**18
    for index in range(1, len(rows)):
        current = rows[index]
        timestamp = float(current[0])
        if timestamp > float(train_end_ms):
            break
        while previous_index < index - 1 and timestamp - float(rows[previous_index][0]) > LOOKBACK_MS:
            previous_index += 1
        previous = rows[previous_index]
        elapsed = timestamp - float(previous[0])
        if elapsed <= 0 or elapsed > LOOKBACK_MS:
            continue
        if timestamp - last_detect_ms < LOOKBACK_MS:
            continue
        prev_hl = _mid(float(previous[2]), float(previous[3]))
        curr_hl = _mid(float(current[2]), float(current[3]))
        prev_bin = _mid(float(previous[4]), float(previous[5]))
        curr_bin = _mid(float(current[4]), float(current[5]))
        hl_move = _move_bps(prev_hl, curr_hl)
        bin_move = _move_bps(prev_bin, curr_bin)
        before_basis = _basis_bps(previous)
        current_basis = _basis_bps(current)
        if None in (hl_move, bin_move, before_basis, current_basis):
            continue
        hl_leads = abs(float(hl_move)) >= float(leader_threshold_bps) and abs(float(bin_move)) <= LAGGER_MAX_MOVE_BPS
        bin_leads = abs(float(bin_move)) >= float(leader_threshold_bps) and abs(float(hl_move)) <= LAGGER_MAX_MOVE_BPS
        if hl_leads == bin_leads:
            continue
        widening = abs(float(current_basis)) - abs(float(before_basis))
        if widening < MIN_BASIS_WIDENING_BPS or abs(float(current_basis)) < MIN_BASIS_WIDENING_BPS:
            continue
        direction = 1 if float(current_basis) > 0 else -1
        result.append(
            {
                "detect_index": index,
                "detect_ts_ms": int(timestamp),
                "leader_venue": "HL" if hl_leads else "BIN",
                "hl_move_bps": float(hl_move),
                "bin_move_bps": float(bin_move),
                "basis_before_bps": float(before_basis),
                "basis_detect_bps": float(current_basis),
                "basis_widening_bps": widening,
                "direction": direction,
            }
        )
        last_detect_ms = int(timestamp)
    return result


def replay_variant_train(
    series: Mapping[str, Sequence[Sequence[Any]]],
    depth: Mapping[str, Sequence[tuple[float, float]]],
    *,
    leader_threshold_bps: float,
    max_hold_ms: int,
    train_end_ms: float,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    trades: list[dict[str, Any]] = []
    diagnostics: dict[str, int] = defaultdict(int)
    seen_ids: set[str] = set()
    for coin in PREDECLARED_COINS:
        rows = sorted(list(series.get(coin, ())), key=lambda row: float(row[0]))
        if len(rows) < 2:
            continue
        coin_depth = sorted(list(depth.get(coin, ())))
        impulses = _detect_impulses(
            rows,
            leader_threshold_bps=float(leader_threshold_bps),
            train_end_ms=float(train_end_ms),
        )
        for impulse in impulses:
            entry_match = _first_at_or_after(
                rows,
                float(impulse["detect_ts_ms"]) + LATENCY_MS,
                max_delay_ms=MAX_ENTRY_DELAY_MS,
            )
            if entry_match is None:
                diagnostics["MISSING_LATENCY_DELAYED_ENTRY"] += 1
                continue
            entry_index, entry = entry_match
            if float(entry[0]) > float(train_end_ms):
                diagnostics["ENTRY_OUTSIDE_TRAIN"] += 1
                continue
            entry_basis = _basis_bps(entry)
            if entry_basis is None or int(impulse["direction"]) * float(entry_basis) <= 0:
                diagnostics["BASIS_REVERSED_BEFORE_ENTRY"] += 1
                continue
            entry_capacity = _capacity_at(coin_depth, float(entry[0]))
            if entry_capacity is None or entry_capacity[0] < NOTIONAL_USD:
                diagnostics["ENTRY_CAPACITY_REJECTED"] += 1
                continue
            exit_row = None
            previous_ts = float(entry[0])
            for candidate in rows[entry_index + 1 :]:
                timestamp = float(candidate[0])
                if timestamp > float(train_end_ms):
                    break
                if timestamp - previous_ts > MAX_OBSERVATION_GAP_MS:
                    diagnostics["OBSERVATION_GAP_INVALIDATED"] += 1
                    exit_row = None
                    break
                previous_ts = timestamp
                candidate_basis = _basis_bps(candidate)
                if candidate_basis is None:
                    continue
                converged = abs(float(candidate_basis)) <= abs(float(entry_basis)) * CONVERGENCE_RATIO
                expired = timestamp - float(entry[0]) >= int(max_hold_ms)
                if converged or expired:
                    exit_row = candidate
                    break
            if exit_row is None:
                diagnostics["NO_CAUSAL_EXIT"] += 1
                continue
            exit_capacity = _capacity_at(coin_depth, float(exit_row[0]))
            if exit_capacity is None or exit_capacity[0] < NOTIONAL_USD:
                diagnostics["EXIT_CAPACITY_REJECTED"] += 1
                continue
            trade = _executable_cycle(
                entry,
                exit_row,
                direction=int(impulse["direction"]),
                notional_usd=NOTIONAL_USD,
                fees_bps=FEES_ROUND_TRIP_BPS,
                entry_capacity=entry_capacity[0],
                exit_capacity=exit_capacity[0],
                detect_ts_ms=float(impulse["detect_ts_ms"]),
            )
            if trade is None or trade.get("LIQUIDATABLE_NET") is not True:
                diagnostics["ECONOMIC_CYCLE_REJECTED"] += 1
                continue
            if trade["trade_id"] in seen_ids:
                diagnostics["DUPLICATE_TRADE_ID"] += 1
                continue
            seen_ids.add(str(trade["trade_id"]))
            trade.update(
                {
                    "coin": coin,
                    "leader_venue": impulse["leader_venue"],
                    "leader_threshold_bps": float(leader_threshold_bps),
                    "max_hold_ms": int(max_hold_ms),
                    "basis_before_bps": impulse["basis_before_bps"],
                    "basis_detect_bps": impulse["basis_detect_bps"],
                    "basis_in_bps": float(entry_basis),
                    "basis_out_bps": float(_basis_bps(exit_row) or 0.0),
                    "depth_freshness_ms": max(entry_capacity[1], exit_capacity[1]),
                }
            )
            trades.append(trade)
            diagnostics["CLOSED_LIQUIDATABLE_TRADE"] += 1
    trades.sort(key=lambda row: (int(row["entry_ts_ms"]), str(row["coin"]), str(row["trade_id"])))
    return trades, dict(diagnostics)


def _placebo_net(trades: Sequence[Mapping[str, Any]]) -> float:
    """Same-time direction-flip placebo, recomputed from recorded executable fills."""
    total = 0.0
    for row in trades:
        entry = row.get("entry_fills") or {}
        exit_ = row.get("exit_fills") or {}
        if not isinstance(entry, Mapping) or not isinstance(exit_, Mapping):
            continue
        direction = -int(row.get("direction") or 0)
        # Reuse the same two observed venue moves with the sign inverted.  Costs stay unchanged.
        gross = float(row.get("gross_pnl_usd") or 0.0)
        fees = float(row.get("fees_usd") or 0.0)
        if direction != 0:
            total += -gross - fees
    return total


def explore_cross_venue_v3_train(
    series: Mapping[str, Sequence[Sequence[Any]]],
    depth: Mapping[str, Sequence[tuple[float, float]]],
    *,
    source_mode: str,
) -> dict[str, Any]:
    """Select a v3 freeze candidate from TRAIN only, never from heldout rows."""

    all_ts = sorted(
        float(row[0])
        for coin in PREDECLARED_COINS
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
            "paper_read_only": True,
            "real_execution": False,
        }
    start_ms, end_ms = all_ts[0], all_ts[-1]
    train_end = start_ms + (end_ms - start_ms) * TRAIN_FRACTION
    grid = [
        (threshold, hold)
        for threshold in LEADER_THRESHOLDS_BPS
        for hold in MAX_HOLDS_MS
    ]
    trial_count = len(PREDECLARED_COINS) * len(grid)
    variants: list[dict[str, Any]] = []
    for threshold, hold in grid:
        trades, diagnostics = replay_variant_train(
            series,
            depth,
            leader_threshold_bps=threshold,
            max_hold_ms=hold,
            train_end_ms=train_end,
        )
        stats = summarize_train_rows(
            trades,
            value_key="net_pnl_usd",
            timestamp_key="entry_ts_ms",
            trial_count=trial_count,
            family_alpha=FAMILY_ALPHA,
        )
        placebo = _placebo_net(trades)
        net = float(stats.get("net_pnl_usd") or 0.0)
        pf = stats.get("profit_factor")
        lcb = stats.get("total_lcb_usd")
        eligible = bool(
            len(trades) >= MIN_TRAIN_TRADES
            and int(stats.get("distinct_days") or 0) >= MIN_DISTINCT_DAYS
            and net > 0.0
            and pf is not None
            and float(pf) > 1.0
            and lcb is not None
            and float(lcb) > 0.0
            and float(stats.get("top_positive_trade_share") or 1.0) <= MAX_TOP_POSITIVE_SHARE
            and net > placebo + 1e-12
        )
        variants.append(
            {
                "leader_threshold_bps": threshold,
                "max_hold_ms": hold,
                "statistics": stats,
                "placebo_net_pnl_usd": placebo,
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
    freeze_candidate = (
        {
            "mechanism": MECHANISM,
            "leader_threshold_bps": selected["leader_threshold_bps"],
            "max_hold_ms": selected["max_hold_ms"],
            "lookback_ms": LOOKBACK_MS,
            "lagger_max_move_bps": LAGGER_MAX_MOVE_BPS,
            "min_basis_widening_bps": MIN_BASIS_WIDENING_BPS,
            "convergence_ratio": CONVERGENCE_RATIO,
            "latency_ms": LATENCY_MS,
            "fees_round_trip_bps": FEES_ROUND_TRIP_BPS,
            "notional_usd": NOTIONAL_USD,
            "source_mode": source_mode,
            "predeclared_coins": list(PREDECLARED_COINS),
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
        "train_bounds": {"start_ms": start_ms, "end_ms": train_end, "full_end_ms": end_ms},
        "fixed_grid": {
            "leader_thresholds_bps": list(LEADER_THRESHOLDS_BPS),
            "max_holds_ms": list(MAX_HOLDS_MS),
            "predeclared_coins": list(PREDECLARED_COINS),
            "trial_count": trial_count,
        },
        "selected": selected,
        "freeze_candidate": freeze_candidate,
        "freeze_candidate_sha256": stable_hash(freeze_candidate) if freeze_candidate else None,
        "variants": variants,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "MECHANISM",
    "PREDECLARED_COINS",
    "SCHEMA_VERSION",
    "explore_cross_venue_v3_train",
    "replay_variant_train",
]
