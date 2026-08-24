"""Pre-freeze multi-asset Lead-Lag research on a strict TRAIN-only wall-clock slice.

This module is research selection, not certification.  The candidate universe and
parameter grid are fixed in code before any result is read.  Only the first 60%
of the recorded market-data wall-clock span is consumed; the remainder is never
loaded into the selection replay.  Every candidate uses measured runtime latency,
recorded Hyperliquid L2, executable bid/ask, top-level capacity, complete costs,
and a Bonferroni-corrected daily lower confidence bound.

PAPER/READ-ONLY only.  A selected candidate merely authorizes a later physical
freeze; it never upgrades the canonical Lead-Lag campaign by itself.
"""
from __future__ import annotations

import bisect
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.backtesting import lead_lag_shadow
from hl_observer.backtesting.lead_lag_source_alignment import (
    _lines,
    _merge_ranges,
    _wall_ms,
    discover_market_tick_windows,
)
from hl_observer.backtesting.train_statistics import stable_hash, summarize_train_rows
from hl_observer.simulation.lead_lag_l2_history import load_market_microstructure_event_windows
from hl_observer.simulation.lead_lag_measured_replay import (
    load_runtime_latency_evidence,
    replay_measured_lead_lag,
)

SCHEMA_VERSION = "hypersmart.lead_lag_multiasset_train.v1"
MECHANISM = "lead_lag_v4_multiasset_measured_taker"
DEFAULT_CANDIDATE_COINS = (
    "BTC", "ETH", "SOL", "XRP", "DOGE", "SUI", "LINK", "AVAX", "INJ", "AAVE", "ONDO"
)
SHOCK_THRESHOLDS_BPS = (8.0, 12.0, 20.0)
HORIZONS_MS = (1_000, 5_000)
TRAIN_FRACTION = 0.60
NOTIONAL_USD = 25.0
MIN_TRAIN_FILLS = 8
MIN_DISTINCT_DAYS = 3
MAX_TOP_POSITIVE_SHARE = 0.60
FAMILY_ALPHA = 0.05


def _in_ranges(timestamp_ms: int, ranges: Sequence[tuple[int, int]]) -> bool:
    if not ranges:
        return False
    starts = [item[0] for item in ranges]
    index = bisect.bisect_right(starts, int(timestamp_ms)) - 1
    return index >= 0 and int(timestamp_ms) <= ranges[index][1]


def _training_ranges(root: str | Path) -> tuple[list[tuple[int, int]], dict[str, Any]]:
    windows = discover_market_tick_windows(root)
    merged = _merge_ranges(windows)
    if not merged:
        return [], {
            "status": "NO_MARKET_WINDOWS",
            "full_start_ms": None,
            "full_end_ms": None,
            "train_end_ms": None,
            "train_fraction": TRAIN_FRACTION,
        }
    start_ms = merged[0][0]
    end_ms = merged[-1][1]
    train_end = int(start_ms + (end_ms - start_ms) * TRAIN_FRACTION)
    train_ranges: list[tuple[int, int]] = []
    for start, end in merged:
        if start > train_end:
            break
        train_ranges.append((start, min(end, train_end)))
    return train_ranges, {
        "status": "TRAIN_CUT_FROZEN_FROM_WALL_CLOCK",
        "full_start_ms": start_ms,
        "full_end_ms": end_ms,
        "train_end_ms": train_end,
        "train_fraction": TRAIN_FRACTION,
        "full_merged_ranges": [list(item) for item in merged],
        "train_ranges": [list(item) for item in train_ranges],
        "heldout_start_ms": train_end + 1,
    }


def load_multiasset_train_tape(
    root: str | Path,
    sources: Sequence[str | Path],
    *,
    coins: Sequence[str] = DEFAULT_CANDIDATE_COINS,
) -> tuple[dict[str, dict[str, list]], dict[str, Any]]:
    """Scan the aligned Binance sources once and retain only the frozen TRAIN span."""

    project_root = Path(root).resolve()
    allowed = {str(coin).upper() for coin in coins}
    train_ranges, split_meta = _training_ranges(project_root)
    tapes: dict[str, list[tuple[int, float, float]]] = {coin: [] for coin in sorted(allowed)}
    seen: set[tuple[Any, ...]] = set()
    consumed: list[str] = []
    lines_read = invalid = outside_train = duplicates = 0
    for value in sources:
        path = Path(value)
        if not path.is_absolute():
            path = project_root / path
        path = path.resolve()
        if not path.is_file():
            continue
        consumed.append(
            path.relative_to(project_root).as_posix()
            if path.is_relative_to(project_root)
            else str(path)
        )
        for line in _lines(path):
            lines_read += 1
            if "BIN_TRADE" not in line:
                continue
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                invalid += 1
                continue
            if not isinstance(row, Mapping) or str(row.get("venue") or "") != "BIN_TRADE":
                continue
            coin = str(row.get("coin") or "").upper()
            if coin not in allowed:
                continue
            timestamp_ms = _wall_ms(dict(row))
            try:
                price = float(row.get("px"))
            except (TypeError, ValueError, OverflowError):
                price = 0.0
            if timestamp_ms is None or price <= 0.0:
                invalid += 1
                continue
            if not _in_ranges(timestamp_ms, train_ranges):
                outside_train += 1
                continue
            side = str(row.get("side") or "").upper()
            direction = 1.0 if side == "BUY" else -1.0
            identity = (
                coin,
                str(row.get("event_id") or ""),
                int(timestamp_ms),
                float(price),
                direction,
                row.get("sz"),
            )
            if identity in seen:
                duplicates += 1
                continue
            seen.add(identity)
            tapes[coin].append((int(timestamp_ms) * 1_000_000, float(price), direction))
    result: dict[str, dict[str, list]] = {}
    for coin, rows in tapes.items():
        rows.sort()
        if rows:
            result[coin] = {"HL": [], "BIN": [], "TRADE": rows}
    return result, {
        "schema_version": "hypersmart.lead_lag_multiasset_train_tape.v1",
        **split_meta,
        "candidate_coins": list(DEFAULT_CANDIDATE_COINS),
        "coins_with_train_trades": sorted(result),
        "sources_read": len(consumed),
        "sources": consumed,
        "lines_read": lines_read,
        "invalid_rows": invalid,
        "rows_outside_frozen_train": outside_train,
        "duplicates_rejected": duplicates,
        "lead_trades_by_coin": {coin: len(streams["TRADE"]) for coin, streams in result.items()},
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_loaded": False,
        "paper_read_only": True,
        "real_execution": False,
    }


def _shock_timestamps(tape: Mapping[str, Mapping[str, list]]) -> list[int]:
    timestamps: set[int] = set()
    minimum_threshold = min(SHOCK_THRESHOLDS_BPS)
    for streams in tape.values():
        trades = list(streams.get("TRADE") or [])
        for timestamp_ns, _direction in lead_lag_shadow.detecter_chocs(
            trades, seuil_bps=minimum_threshold
        ):
            timestamps.add(int(timestamp_ns // 1_000_000))
    return sorted(timestamps)


def _rows_from_ledgers(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    ledgers = report.get("ledgers")
    if not isinstance(ledgers, Mapping):
        return result
    for label in ("IS", "OOS", "FORWARD"):
        rows = ledgers.get(label)
        if not isinstance(rows, list):
            continue
        signals: dict[str, tuple[int, str]] = {}
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            trade_id = str(row.get("trade_id") or "")
            if not trade_id:
                continue
            if row.get("evt") == "SIGNAL":
                signals[trade_id] = (int(row.get("ts") or 0), str(row.get("coin") or ""))
            elif row.get("evt") == "PNL" and row.get("LIQUIDATABLE_NET") is True:
                try:
                    net = float(row.get("pnl_usd"))
                except (TypeError, ValueError, OverflowError):
                    continue
                timestamp, coin = signals.get(trade_id, (0, ""))
                if timestamp > 0:
                    result.append(
                        {
                            "trade_id": trade_id,
                            "timestamp_ms": timestamp,
                            "coin": coin,
                            "net_pnl_usd": net,
                            "internal_train_fold": label,
                        }
                    )
    return result


def _score_report(
    report: Mapping[str, Any],
    *,
    coin: str,
    threshold_bps: float,
    horizon_ms: int,
    trial_count: int,
) -> dict[str, Any]:
    rows = _rows_from_ledgers(report)
    stats = summarize_train_rows(
        rows,
        value_key="net_pnl_usd",
        timestamp_key="timestamp_ms",
        trial_count=trial_count,
        family_alpha=FAMILY_ALPHA,
    )
    segments = report.get("segments") if isinstance(report.get("segments"), Mapping) else {}
    internal_fold_nets = {
        label: float((segments.get(label) or {}).get("net") or 0.0)
        for label in ("IS", "OOS", "FORWARD")
    }
    placebo_net = float(report.get("placebo_net") or 0.0)
    net = float(stats.get("net_pnl_usd") or 0.0)
    pf = stats.get("profit_factor")
    lcb = stats.get("total_lcb_usd")
    eligible = bool(
        report.get("costs_measured") is True
        and int(stats.get("sample_count") or 0) >= MIN_TRAIN_FILLS
        and int(stats.get("distinct_days") or 0) >= MIN_DISTINCT_DAYS
        and net > 0.0
        and pf is not None
        and float(pf) > 1.0
        and lcb is not None
        and float(lcb) > 0.0
        and float(stats.get("top_positive_trade_share") or 1.0) <= MAX_TOP_POSITIVE_SHARE
        and net > placebo_net + 1e-12
        and all(value > 0.0 for value in internal_fold_nets.values())
    )
    return {
        "coin": str(coin).upper(),
        "shock_threshold_bps": float(threshold_bps),
        "horizon_ms": int(horizon_ms),
        "statistics": stats,
        "internal_train_fold_nets": internal_fold_nets,
        "placebo_net_pnl_usd": placebo_net,
        "coverage": dict(report.get("coverage") or {}),
        "signals": int(report.get("signals") or 0),
        "decision_counts": dict(report.get("decision_counts") or {}),
        "raw_observation_diagnostics": dict(
            report.get("raw_observation_diagnostics") or {}
        ),
        "eligible": eligible,
    }


def explore_lead_lag_multiasset_train(
    root: str | Path,
    lead_sources: Sequence[str | Path],
    *,
    candidate_coins: Sequence[str] = DEFAULT_CANDIDATE_COINS,
) -> dict[str, Any]:
    """Explore the fixed grid without loading the chronological heldout span."""

    tape, tape_meta = load_multiasset_train_tape(root, lead_sources, coins=candidate_coins)
    shock_ts = _shock_timestamps(tape)
    l2_history, _public_trades, l2_meta = load_market_microstructure_event_windows(
        root,
        shock_ts,
        before_ms=1_000,
        after_ms=max(HORIZONS_MS) + 2_000,
    )
    latency = load_runtime_latency_evidence(root)
    variants: list[dict[str, Any]] = []
    trial_count = max(1, len(candidate_coins) * len(SHOCK_THRESHOLDS_BPS) * len(HORIZONS_MS))
    for coin in candidate_coins:
        selected_coin = str(coin).upper()
        if selected_coin not in tape:
            continue
        for threshold in SHOCK_THRESHOLDS_BPS:
            for horizon in HORIZONS_MS:
                report = replay_measured_lead_lag(
                    {selected_coin: tape[selected_coin]},
                    {selected_coin: list(l2_history.get(selected_coin, ()))},
                    shock_threshold_bps=float(threshold),
                    horizon_ms=int(horizon),
                    latency_evidence=latency,
                    notional_usd=NOTIONAL_USD,
                    min_history=5,
                    min_expected_net_bps=0.0,
                    min_episodes=1,
                )
                variants.append(
                    _score_report(
                        report,
                        coin=selected_coin,
                        threshold_bps=float(threshold),
                        horizon_ms=int(horizon),
                        trial_count=trial_count,
                    )
                )
    eligible = [row for row in variants if row["eligible"]]
    selected = max(
        eligible,
        key=lambda row: (
            float((row["statistics"] or {}).get("total_lcb_usd") or 0.0),
            float((row["statistics"] or {}).get("net_pnl_usd") or 0.0),
            int((row["statistics"] or {}).get("sample_count") or 0),
        ),
        default=None,
    )
    freeze_payload = (
        {
            "mechanism": MECHANISM,
            "coin": selected["coin"],
            "shock_threshold_bps": selected["shock_threshold_bps"],
            "horizon_ms": selected["horizon_ms"],
            "notional_usd": NOTIONAL_USD,
            "candidate_universe": list(DEFAULT_CANDIDATE_COINS),
            "grid": {
                "shock_thresholds_bps": list(SHOCK_THRESHOLDS_BPS),
                "horizons_ms": list(HORIZONS_MS),
            },
            "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        }
        if selected is not None
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
        "candidate_universe": list(DEFAULT_CANDIDATE_COINS),
        "fixed_grid": {
            "shock_thresholds_bps": list(SHOCK_THRESHOLDS_BPS),
            "horizons_ms": list(HORIZONS_MS),
            "notional_usd": NOTIONAL_USD,
            "trial_count": trial_count,
        },
        "selected": selected,
        "freeze_candidate": freeze_payload,
        "freeze_candidate_sha256": stable_hash(freeze_payload) if freeze_payload else None,
        "variants": variants,
        "train_tape": tape_meta,
        "microstructure": l2_meta,
        "latency_evidence": latency,
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "DEFAULT_CANDIDATE_COINS",
    "HORIZONS_MS",
    "MECHANISM",
    "SCHEMA_VERSION",
    "SHOCK_THRESHOLDS_BPS",
    "explore_lead_lag_multiasset_train",
    "load_multiasset_train_tape",
]
