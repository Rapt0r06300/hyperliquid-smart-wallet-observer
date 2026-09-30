"""TRAIN-only Lead-Lag research using causal Binance BBO repricing shocks.

This representation is deliberately separate from the existing Binance trade
shock families.  It derives mid-price and top-of-book microprice shocks from
recorded Binance BBO rows and settles them on recorded Hyperliquid bid/ask with
the measured-latency replay.  Only the first 60% of the source wall-clock span
is loaded; heldout rows are never exposed to selection.

PAPER/READ-ONLY only.  This module has no exchange or order client.
"""
from __future__ import annotations

import json
import math
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.backtesting.lead_lag_multiasset_ranges import in_ranges
from hl_observer.backtesting.lead_lag_multiasset_train import _score_report
from hl_observer.backtesting.lead_lag_multitape import discover_sources
from hl_observer.backtesting.lead_lag_source_alignment import (
    _lines,
    _merge_ranges,
    _wall_ms,
    infer_bbo_source_windows,
)
from hl_observer.backtesting.train_statistics import stable_hash
from hl_observer.simulation.lead_lag_measured_replay import (
    ADMISSION_PREDECLARED_ALL_SIGNALS,
    load_runtime_latency_evidence,
    replay_measured_lead_lag,
)

SCHEMA_VERSION = "hypersmart.lead_lag_bbo_repricing_train.v1"
MECHANISM = "lead_lag_v10_binance_bbo_repricing_measured_taker"
HYPOTHESIS_ID = "H-LL-BBO-REPRICING-MICROPRICE-V1"
CANDIDATE_COINS = ("BTC", "ETH", "SOL")
REPRESENTATIONS = ("mid", "microprice")
SHOCK_WINDOWS_MS = (100, 250, 500)
SHOCK_THRESHOLDS_BPS = (1.0, 2.0, 4.0)
HORIZONS_MS = (250, 500, 1_000)
TRAIN_FRACTION = 0.60
NOTIONAL_USD = 25.0
MIN_TRAIN_FILLS = 30
MIN_DISTINCT_DAYS = 3
TARGET_DAILY_NET_USD = 4.0
PRIOR_FAMILY_TRIAL_COUNT = 2_934
NEW_TRIAL_COUNT = (
    len(CANDIDATE_COINS)
    * len(REPRESENTATIONS)
    * len(SHOCK_WINDOWS_MS)
    * len(SHOCK_THRESHOLDS_BPS)
    * len(HORIZONS_MS)
)
BONFERRONI_TRIAL_COUNT = PRIOR_FAMILY_TRIAL_COUNT + NEW_TRIAL_COUNT


def _finite(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix() if path.is_relative_to(root) else str(path)


def _source_training_ranges(
    root: str | Path,
    sources: Sequence[str | Path],
    *,
    train_fraction: float = TRAIN_FRACTION,
) -> tuple[list[tuple[int, int]], dict[str, Any]]:
    """Freeze a wall-clock TRAIN prefix directly from immutable BBO shards."""

    windows = infer_bbo_source_windows(root, sources)
    merged = _merge_ranges(windows)
    if not merged:
        return [], {
            "status": "NO_TIMESTAMPED_BBO_SHARDS",
            "full_start_ms": None,
            "full_end_ms": None,
            "train_end_ms": None,
            "heldout_start_ms": None,
            "train_fraction": float(train_fraction),
            "full_merged_ranges": [],
            "train_ranges": [],
        }
    full_start_ms = int(merged[0][0])
    full_end_ms = int(merged[-1][1])
    train_end_ms = int(
        full_start_ms + (full_end_ms - full_start_ms) * float(train_fraction)
    )
    train_ranges: list[tuple[int, int]] = []
    for start_ms, end_ms in merged:
        if int(start_ms) > train_end_ms:
            break
        train_ranges.append((int(start_ms), min(int(end_ms), train_end_ms)))
    return train_ranges, {
        "status": "TRAIN_CUT_FROZEN_FROM_BBO_WALL_CLOCK",
        "full_start_ms": full_start_ms,
        "full_end_ms": full_end_ms,
        "train_end_ms": train_end_ms,
        "heldout_start_ms": train_end_ms + 1,
        "train_fraction": float(train_fraction),
        "full_merged_ranges": [list(item) for item in merged],
        "train_ranges": [list(item) for item in train_ranges],
    }


def _bbo_value(row: Mapping[str, Any], representation: str) -> float | None:
    bid = _finite(row.get("bid"))
    ask = _finite(row.get("ask"))
    if bid is None or ask is None or bid <= 0.0 or ask < bid:
        return None
    if representation == "mid":
        return 0.5 * (bid + ask)
    if representation != "microprice":
        raise ValueError("representation must be 'mid' or 'microprice'")
    bid_size = _finite(row.get("bid_size"))
    ask_size = _finite(row.get("ask_size"))
    if (
        bid_size is None
        or ask_size is None
        or bid_size <= 0.0
        or ask_size <= 0.0
    ):
        return None
    return (ask * bid_size + bid * ask_size) / (bid_size + ask_size)


def detect_bbo_repricing_shocks(
    rows: Sequence[Mapping[str, Any]],
    *,
    representation: str,
    window_ms: int,
    threshold_bps: float,
) -> tuple[list[tuple[int, float]], dict[str, Any]]:
    """Detect causal window returns without crossing recorded source sessions."""

    if representation not in REPRESENTATIONS:
        raise ValueError("unsupported BBO representation")
    if int(window_ms) <= 0 or float(threshold_bps) <= 0.0:
        raise ValueError("window_ms and threshold_bps must be positive")

    grouped: dict[str, list[tuple[int, float]]] = defaultdict(list)
    invalid_rows = 0
    for raw in rows:
        source_id = str(raw.get("source_id") or "")
        try:
            timestamp_ms = int(raw.get("ts_ms") or 0)
        except (TypeError, ValueError, OverflowError):
            timestamp_ms = 0
        value = _bbo_value(raw, representation)
        if not source_id or timestamp_ms <= 0 or value is None or value <= 0.0:
            invalid_rows += 1
            continue
        grouped[source_id].append((timestamp_ms, float(value)))

    signals: set[tuple[int, float]] = set()
    causal_evaluations = no_baseline = 0
    for source_rows in grouped.values():
        source_rows.sort(key=lambda item: (item[0], item[1]))
        timestamps = [item[0] for item in source_rows]
        for index, (timestamp_ms, value) in enumerate(source_rows):
            baseline_index = bisect_right(
                timestamps, int(timestamp_ms) - int(window_ms), hi=index
            ) - 1
            if baseline_index < 0:
                no_baseline += 1
                continue
            baseline_ts_ms, baseline = source_rows[baseline_index]
            if baseline_ts_ms >= timestamp_ms or baseline <= 0.0:
                no_baseline += 1
                continue
            causal_evaluations += 1
            move_bps = (value / baseline - 1.0) * 10_000.0
            if abs(move_bps) + 1e-12 >= float(threshold_bps):
                signals.add(
                    (int(timestamp_ms) * 1_000_000, 1.0 if move_bps > 0.0 else -1.0)
                )
    ordered = sorted(signals)
    return ordered, {
        "schema_version": "hypersmart.lead_lag_bbo_shock_detector.v1",
        "representation": representation,
        "window_ms": int(window_ms),
        "threshold_bps": float(threshold_bps),
        "source_sessions": len(grouped),
        "input_rows": len(rows),
        "invalid_rows": invalid_rows,
        "causal_evaluations": causal_evaluations,
        "rows_without_causal_baseline": no_baseline,
        "signals": len(ordered),
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_loaded": False,
        "paper_read_only": True,
        "real_execution": False,
    }


def load_bbo_train_tape(
    root: str | Path,
    sources: Sequence[str | Path],
    *,
    coins: Sequence[str] = CANDIDATE_COINS,
) -> tuple[dict[str, dict[str, list]], dict[str, Any]]:
    """Load aligned Binance and Hyperliquid BBO from the frozen TRAIN prefix."""

    project_root = Path(root).resolve()
    allowed = {str(coin).upper() for coin in coins}
    train_ranges, split_meta = _source_training_ranges(project_root, sources)
    eligible_paths = {
        window.path.resolve()
        for window in infer_bbo_source_windows(project_root, sources)
        if any(
            int(window.start_ms) <= int(end_ms)
            and int(window.end_ms) >= int(start_ms)
            for start_ms, end_ms in train_ranges
        )
    }
    binance: dict[str, list[dict[str, Any]]] = defaultdict(list)
    books: dict[str, list[dict[str, Any]]] = defaultdict(list)
    source_ids: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"BIN": set(), "HL": set()}
    )
    last_binance_state: dict[
        tuple[str, str], tuple[float, float, float | None, float | None]
    ] = {}
    seen: set[tuple[Any, ...]] = set()
    lines_read = invalid_rows = outside_train = duplicates = collapsed_binance = 0
    consumed: list[str] = []
    for value in sources:
        path = Path(value)
        if not path.is_absolute():
            path = project_root / path
        path = path.resolve()
        if not path.is_file():
            continue
        if path not in eligible_paths:
            continue
        source_id = _relative(project_root, path)
        consumed.append(source_id)
        for line in _lines(path):
            lines_read += 1
            if '"venue"' not in line:
                continue
            try:
                raw = json.loads(line)
            except (TypeError, ValueError):
                invalid_rows += 1
                continue
            if not isinstance(raw, Mapping):
                invalid_rows += 1
                continue
            venue = str(raw.get("venue") or "")
            coin = str(raw.get("coin") or "").upper()
            if venue not in {"BIN", "HL"} or coin not in allowed:
                continue
            timestamp_ms = _wall_ms(dict(raw))
            bid = _finite(raw.get("bid"))
            ask = _finite(raw.get("ask"))
            bid_size = _finite(raw.get("bid_sz", raw.get("bid_size")))
            ask_size = _finite(raw.get("ask_sz", raw.get("ask_size")))
            if (
                timestamp_ms is None
                or bid is None
                or ask is None
                or bid <= 0.0
                or ask < bid
                or (
                    venue == "HL"
                    and (
                        bid_size is None
                        or ask_size is None
                        or bid_size <= 0.0
                        or ask_size <= 0.0
                    )
                )
            ):
                invalid_rows += 1
                continue
            if not in_ranges(int(timestamp_ms), train_ranges):
                outside_train += 1
                continue
            if venue == "BIN":
                state_key = (coin, source_id)
                current_state = (
                    float(bid),
                    float(ask),
                    bid_size,
                    ask_size,
                )
                if last_binance_state.get(state_key) == current_state:
                    collapsed_binance += 1
                    continue
                last_binance_state[state_key] = current_state
            identity = (
                venue,
                coin,
                str(raw.get("event_id") or ""),
                int(timestamp_ms),
                float(bid),
                float(ask),
                bid_size,
                ask_size,
            )
            if identity in seen:
                duplicates += 1
                continue
            seen.add(identity)
            row = {
                "coin": coin,
                "ts_ms": int(timestamp_ms),
                "observable_at_ms": int(timestamp_ms),
                "exchange_ts_ms": raw.get("ts_ex"),
                "bid": float(bid),
                "ask": float(ask),
                "bid_size": float(bid_size) if bid_size is not None else None,
                "ask_size": float(ask_size) if ask_size is not None else None,
                "bid_top_usd": (
                    float(bid) * float(bid_size) if bid_size is not None else None
                ),
                "ask_top_usd": (
                    float(ask) * float(ask_size) if ask_size is not None else None
                ),
                "bid_depth_usd": (
                    float(bid) * float(bid_size) if bid_size is not None else None
                ),
                "ask_depth_usd": (
                    float(ask) * float(ask_size) if ask_size is not None else None
                ),
                "connection_id": raw.get("connection_id"),
                "sequence": raw.get("sequence"),
                "event_id": raw.get("event_id"),
                "source_id": source_id,
                "data_origin": "RECORDED_REAL",
                "read_only": True,
                "real_execution": False,
            }
            if venue == "BIN":
                binance[coin].append(row)
                source_ids[coin]["BIN"].add(source_id)
            else:
                books[coin].append(row)
                source_ids[coin]["HL"].add(source_id)

    result: dict[str, dict[str, list]] = {}
    for coin in sorted(allowed):
        shared = source_ids[coin]["BIN"] & source_ids[coin]["HL"]
        if not shared:
            continue
        bin_rows = sorted(
            (row for row in binance[coin] if str(row["source_id"]) in shared),
            key=lambda row: (int(row["ts_ms"]), str(row["event_id"] or "")),
        )
        hl_rows = sorted(
            (row for row in books[coin] if str(row["source_id"]) in shared),
            key=lambda row: (int(row["ts_ms"]), str(row["event_id"] or "")),
        )
        if bin_rows and hl_rows:
            result[coin] = {
                "BIN_BBO": bin_rows,
                "HL_BOOK": hl_rows,
                "BIN_SOURCE_IDS": sorted(shared),
                "HL_BOOK_SOURCE_IDS": sorted(shared),
            }
    return result, {
        "schema_version": "hypersmart.lead_lag_bbo_train_tape.v1",
        **split_meta,
        "candidate_coins": list(coins),
        "sources_read": len(consumed),
        "sources": consumed,
        "lines_read": lines_read,
        "invalid_rows": invalid_rows,
        "rows_outside_frozen_train": outside_train,
        "duplicates_rejected": duplicates,
        "binance_unchanged_updates_collapsed": collapsed_binance,
        "coins_with_common_bbo": sorted(result),
        "binance_bbo_by_coin": {
            coin: len(streams["BIN_BBO"]) for coin, streams in result.items()
        },
        "hl_books_by_coin": {
            coin: len(streams["HL_BOOK"]) for coin, streams in result.items()
        },
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_loaded": False,
        "paper_read_only": True,
        "real_execution": False,
    }


def explore_lead_lag_bbo_repricing_train(
    root: str | Path,
    sources: Sequence[str | Path] | None = None,
    *,
    candidate_coins: Sequence[str] = CANDIDATE_COINS,
) -> dict[str, Any]:
    """Evaluate the 162 fixed BBO-repricing variants on TRAIN only."""

    project_root = Path(root).resolve()
    selected_sources = list(sources) if sources is not None else discover_sources(project_root)
    tape, tape_meta = load_bbo_train_tape(
        project_root, selected_sources, coins=candidate_coins
    )
    latency = load_runtime_latency_evidence(project_root)
    variants: list[dict[str, Any]] = []
    shock_cache: dict[
        tuple[str, str, int, float], tuple[list[tuple[int, float]], dict[str, Any]]
    ] = {}
    for coin in candidate_coins:
        selected_coin = str(coin).upper()
        streams = tape.get(selected_coin)
        if not streams:
            continue
        bin_rows = list(streams.get("BIN_BBO") or [])
        hl_rows = list(streams.get("HL_BOOK") or [])
        if len(bin_rows) < 2 or not hl_rows:
            continue
        synthetic_tape = {
            selected_coin: {
                "HL": [],
                "BIN": [],
                "TRADE": [
                    (
                        int(row["ts_ms"]) * 1_000_000,
                        float(_bbo_value(row, "mid") or 0.0),
                        1.0,
                    )
                    for row in bin_rows
                ],
            }
        }
        for representation in REPRESENTATIONS:
            for window_ms in SHOCK_WINDOWS_MS:
                for threshold_bps in SHOCK_THRESHOLDS_BPS:
                    cache_key = (
                        selected_coin,
                        representation,
                        int(window_ms),
                        float(threshold_bps),
                    )
                    shocks, detector_diagnostics = detect_bbo_repricing_shocks(
                        bin_rows,
                        representation=representation,
                        window_ms=int(window_ms),
                        threshold_bps=float(threshold_bps),
                    )
                    shock_cache[cache_key] = (shocks, detector_diagnostics)
                    for horizon_ms in HORIZONS_MS:
                        replay = replay_measured_lead_lag(
                            synthetic_tape,
                            {selected_coin: hl_rows},
                            shock_threshold_bps=float(threshold_bps),
                            horizon_ms=int(horizon_ms),
                            latency_evidence=latency,
                            notional_usd=NOTIONAL_USD,
                            min_history=0,
                            min_expected_net_bps=0.0,
                            direction_multiplier=1,
                            shock_window_ms=float(window_ms),
                            admission_policy=ADMISSION_PREDECLARED_ALL_SIGNALS,
                            precomputed_shocks={selected_coin: shocks},
                            inputs_sorted=True,
                            min_episodes=1,
                        )
                        scored = _score_report(
                            replay,
                            coin=selected_coin,
                            threshold_bps=float(threshold_bps),
                            horizon_ms=int(horizon_ms),
                            trial_count=BONFERRONI_TRIAL_COUNT,
                            mechanism=MECHANISM,
                            direction_multiplier=1,
                            min_train_fills=MIN_TRAIN_FILLS,
                            shock_window_ms=float(window_ms),
                            admission_policy=ADMISSION_PREDECLARED_ALL_SIGNALS,
                            economic_predeclaration_id=HYPOTHESIS_ID,
                        )
                        statistics = dict(scored.get("statistics") or {})
                        days = int(statistics.get("distinct_days") or 0)
                        daily_mean = (
                            float(statistics.get("net_pnl_usd") or 0.0) / days
                            if days > 0
                            else None
                        )
                        daily_target_met = bool(
                            daily_mean is not None
                            and daily_mean + 1e-12 >= TARGET_DAILY_NET_USD
                        )
                        scored.update(
                            {
                                "representation": representation,
                                "direction_policy": "BBO_REPRICING_CONTINUATION",
                                "detector_diagnostics": detector_diagnostics,
                                "daily_mean_net_pnl_usd": daily_mean,
                                "target_daily_net_usd": TARGET_DAILY_NET_USD,
                                "daily_target_met": daily_target_met,
                                "eligible": bool(scored.get("eligible"))
                                and daily_target_met,
                            }
                        )
                        variants.append(scored)
    eligible = [row for row in variants if row.get("eligible") is True]
    selected = max(
        eligible,
        key=lambda row: (
            float((row.get("statistics") or {}).get("total_lcb_usd") or 0.0),
            float(row.get("daily_mean_net_pnl_usd") or 0.0),
            int((row.get("statistics") or {}).get("sample_count") or 0),
        ),
        default=None,
    )
    freeze_candidate = (
        {
            "hypothesis_id": HYPOTHESIS_ID,
            "mechanism": MECHANISM,
            "coin": selected["coin"],
            "representation": selected["representation"],
            "shock_window_ms": selected["shock_window_ms"],
            "shock_threshold_bps": selected["shock_threshold_bps"],
            "horizon_ms": selected["horizon_ms"],
            "notional_usd": NOTIONAL_USD,
            "research_family_trial_count": BONFERRONI_TRIAL_COUNT,
            "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        }
        if selected is not None
        else None
    )
    best_diagnostic = max(
        variants,
        key=lambda row: (
            int((row.get("statistics") or {}).get("sample_count") or 0) > 0,
            float((row.get("statistics") or {}).get("net_pnl_usd") or 0.0),
            int((row.get("statistics") or {}).get("sample_count") or 0),
        ),
        default=None,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "hypothesis_id": HYPOTHESIS_ID,
        "mechanism": MECHANISM,
        "status": "TRAIN_ELIGIBLE_TO_FREEZE" if selected else "NO_ROBUST_TRAIN_CANDIDATE",
        "selection_eligible": selected is not None,
        "physical_freeze_allowed": selected is not None,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_evaluated": False,
        "fixed_grid": {
            "candidate_coins": list(CANDIDATE_COINS),
            "representations": list(REPRESENTATIONS),
            "shock_windows_ms": list(SHOCK_WINDOWS_MS),
            "shock_thresholds_bps": list(SHOCK_THRESHOLDS_BPS),
            "horizons_ms": list(HORIZONS_MS),
            "notional_usd": NOTIONAL_USD,
            "minimum_train_fills": MIN_TRAIN_FILLS,
            "minimum_distinct_days": MIN_DISTINCT_DAYS,
            "target_daily_net_usd": TARGET_DAILY_NET_USD,
            "prior_family_trial_count": PRIOR_FAMILY_TRIAL_COUNT,
            "new_trial_count": NEW_TRIAL_COUNT,
            "bonferroni_trial_count": BONFERRONI_TRIAL_COUNT,
        },
        "source_meta": tape_meta,
        "latency_evidence": latency,
        "evaluated_variants": len(variants),
        "variants": variants,
        "selected": selected,
        "best_diagnostic": best_diagnostic,
        "freeze_candidate": freeze_candidate,
        "freeze_candidate_sha256": (
            stable_hash(freeze_candidate) if freeze_candidate is not None else None
        ),
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = [
    "BONFERRONI_TRIAL_COUNT",
    "CANDIDATE_COINS",
    "HORIZONS_MS",
    "NEW_TRIAL_COUNT",
    "REPRESENTATIONS",
    "SHOCK_THRESHOLDS_BPS",
    "SHOCK_WINDOWS_MS",
    "detect_bbo_repricing_shocks",
    "explore_lead_lag_bbo_repricing_train",
    "load_bbo_train_tape",
]
