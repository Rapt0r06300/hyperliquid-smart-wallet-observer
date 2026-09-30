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

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from hl_observer.backtesting import lead_lag_shadow
from hl_observer.backtesting.lead_lag_book_confirmation import (
    HORIZONS_MS as BOOK_CONFIRMATION_HORIZONS_MS,
)
from hl_observer.backtesting.lead_lag_book_confirmation import (
    IMBALANCE_THRESHOLDS as BOOK_CONFIRMATION_IMBALANCE_THRESHOLDS,
)
from hl_observer.backtesting.lead_lag_book_confirmation import (
    MAX_BOOK_AGE_MS as BOOK_CONFIRMATION_MAX_BOOK_AGE_MS,
)
from hl_observer.backtesting.lead_lag_book_confirmation import (
    MECHANISM as BOOK_CONFIRMATION_MECHANISM,
)
from hl_observer.backtesting.lead_lag_book_confirmation import (
    MIN_TRAIN_FILLS as BOOK_CONFIRMATION_MIN_TRAIN_FILLS,
)
from hl_observer.backtesting.lead_lag_book_confirmation import (
    SHOCK_THRESHOLDS_BPS as BOOK_CONFIRMATION_SHOCK_THRESHOLDS_BPS,
)
from hl_observer.backtesting.lead_lag_book_confirmation import (
    SHOCK_WINDOWS_MS as BOOK_CONFIRMATION_SHOCK_WINDOWS_MS,
)
from hl_observer.backtesting.lead_lag_book_confirmation import (
    book_confirmation_trial_count,
    confirm_shocks_with_causal_book,
)
from hl_observer.backtesting.lead_lag_multiasset_ranges import (
    in_ranges as _in_ranges_impl,
)
from hl_observer.backtesting.lead_lag_multiasset_tape import (
    load_multiasset_train_tape as _load_multiasset_train_tape_impl,
)
from hl_observer.backtesting.lead_lag_multiasset_ranges import (
    training_ranges as _training_ranges_impl,
)
from hl_observer.backtesting.lead_lag_multiasset_scoring import (
    independent_train_rows as _independent_train_rows_impl,
)
from hl_observer.backtesting.lead_lag_multiasset_scoring import (
    rows_from_ledgers as _rows_from_ledgers_impl,
)
from hl_observer.backtesting.lead_lag_multiasset_scoring import (
    score_report as _score_report_impl,
)
from hl_observer.backtesting.lead_lag_multiasset_scoring import (
    shock_timestamps as _shock_timestamps_impl,
)
from hl_observer.backtesting.lead_lag_reference_residual_grid import (
    REFERENCE_RESIDUAL_BETAS,
    REFERENCE_RESIDUAL_DIRECTION_POLICIES,
    REFERENCE_RESIDUAL_HORIZONS_MS,
    REFERENCE_RESIDUAL_MECHANISM,
    REFERENCE_RESIDUAL_MIN_TRAIN_FILLS,
    REFERENCE_RESIDUAL_THRESHOLDS_BPS,
    REFERENCE_RESIDUAL_WINDOWS_MS,
    detect_reference_residual_shocks,
    research_family_trial_count,
)
from hl_observer.backtesting.lead_lag_source_alignment import (
    discover_market_tick_windows,
    infer_bbo_source_windows,
)
from hl_observer.backtesting.train_statistics import stable_hash, summarize_train_rows
from hl_observer.simulation.lead_lag_l2_history import load_market_microstructure_event_windows
from hl_observer.simulation.lead_lag_measured_replay import (
    ADMISSION_PREDECLARED_ALL_SIGNALS,
    ADMISSION_PRIOR_MEAN_POSITIVE,
    load_runtime_latency_evidence,
    replay_measured_lead_lag,
)

SCHEMA_VERSION = "hypersmart.lead_lag_multiasset_train.v2"
MECHANISM = "lead_lag_v4_multiasset_measured_taker"
EXTREME_REVERSAL_MECHANISM = "lead_lag_v5_extreme_shock_reversal_taker"
WINDOW_CONTINUATION_MECHANISM = "lead_lag_v6_cumulative_window_continuation_taker"
CROSS_ASSET_MECHANISM = "lead_lag_v7_major_to_alt_cumulative_continuation_taker"
DEFAULT_CANDIDATE_COINS = ("BTC", "ETH", "SOL", "XRP", "DOGE", "SUI", "LINK", "AVAX", "INJ", "AAVE", "ONDO")
SHOCK_THRESHOLDS_BPS = (8.0, 12.0, 20.0)
DIAGNOSTIC_ONLY_SHOCK_THRESHOLD_BPS = 8.0
HORIZONS_MS = (1_000, 5_000)
EXTREME_REVERSAL_SHOCK_THRESHOLDS_BPS = (20.0, 30.0, 50.0)
EXTREME_REVERSAL_HORIZONS_MS = (1_000, 5_000, 15_000)
WINDOW_SHOCK_WINDOWS_MS = (250, 1_000)
WINDOW_SHOCK_THRESHOLDS_BPS = (4.0, 8.0, 12.0)
WINDOW_HORIZONS_MS = (1_000, 5_000)
TRAIN_FRACTION = 0.60
NOTIONAL_USD = 25.0
MIN_TRAIN_FILLS = 8
EXTREME_REVERSAL_MIN_TRAIN_FILLS = 30
WINDOW_MIN_TRAIN_FILLS = 30
CROSS_ASSET_LEADERS = ("BTC", "ETH")
CROSS_ASSET_FOLLOWERS = ("SOL", "XRP", "DOGE", "SUI", "LINK", "AVAX", "INJ", "AAVE", "ONDO")
CROSS_ASSET_SHOCK_WINDOWS_MS = (250, 1_000)
CROSS_ASSET_SHOCK_THRESHOLDS_BPS = (8.0, 12.0, 20.0)
CROSS_ASSET_HORIZONS_MS = (1_000, 5_000, 15_000)
CROSS_ASSET_MIN_TRAIN_FILLS = 30
MIN_DISTINCT_DAYS = 3
MAX_TOP_POSITIVE_SHARE = 0.60
FAMILY_ALPHA = 0.05

TRAIN_HYPOTHESES = (
    {
        "mechanism": MECHANISM,
        "direction_multiplier": 1,
        "direction_policy": "SHOCK_CONTINUATION",
        "shock_thresholds_bps": SHOCK_THRESHOLDS_BPS,
        "horizons_ms": HORIZONS_MS,
        "min_train_fills": MIN_TRAIN_FILLS,
        "shock_windows_ms": (None,),
        "admission_policy": ADMISSION_PRIOR_MEAN_POSITIVE,
    },
    {
        "mechanism": EXTREME_REVERSAL_MECHANISM,
        "direction_multiplier": -1,
        "direction_policy": "EXTREME_SHOCK_REVERSAL",
        "shock_thresholds_bps": EXTREME_REVERSAL_SHOCK_THRESHOLDS_BPS,
        "horizons_ms": EXTREME_REVERSAL_HORIZONS_MS,
        "min_train_fills": EXTREME_REVERSAL_MIN_TRAIN_FILLS,
        "shock_windows_ms": (None,),
        "admission_policy": ADMISSION_PRIOR_MEAN_POSITIVE,
    },
    {
        "mechanism": WINDOW_CONTINUATION_MECHANISM,
        "direction_multiplier": 1,
        "direction_policy": "CUMULATIVE_WINDOW_CONTINUATION",
        "shock_thresholds_bps": WINDOW_SHOCK_THRESHOLDS_BPS,
        "horizons_ms": WINDOW_HORIZONS_MS,
        "min_train_fills": WINDOW_MIN_TRAIN_FILLS,
        "shock_windows_ms": WINDOW_SHOCK_WINDOWS_MS,
        "admission_policy": ADMISSION_PREDECLARED_ALL_SIGNALS,
    },
)


def _planned_cross_asset_pairs(candidate_coins: Sequence[str]) -> list[tuple[str, str]]:
    allowed = {str(coin).upper() for coin in candidate_coins}
    return [
        (leader, follower)
        for leader in CROSS_ASSET_LEADERS
        for follower in CROSS_ASSET_FOLLOWERS
        if leader in allowed and follower in allowed and leader != follower
    ]


_in_ranges = _in_ranges_impl


def _training_ranges(
    root: str | Path,
    lead_sources: Sequence[str | Path] = (),
) -> tuple[list[tuple[int, int]], dict[str, Any]]:
    return _training_ranges_impl(
        root,
        train_fraction=TRAIN_FRACTION,
        window_discovery=discover_market_tick_windows,
        eligible_windows=infer_bbo_source_windows(root, lead_sources),
    )


def load_multiasset_train_tape(
    root: str | Path,
    sources: Sequence[str | Path],
    *,
    coins: Sequence[str] = DEFAULT_CANDIDATE_COINS,
) -> tuple[dict[str, dict[str, list]], dict[str, Any]]:
    return _load_multiasset_train_tape_impl(
        root,
        sources,
        coins=coins,
        default_candidate_coins=DEFAULT_CANDIDATE_COINS,
        training_ranges=_training_ranges,
        in_ranges=_in_ranges,
    )


def _shock_timestamps(tape: Mapping[str, Mapping[str, list]]) -> list[int]:
    return _shock_timestamps_impl(
        tape,
        minimum_threshold=min(SHOCK_THRESHOLDS_BPS),
        detector=lead_lag_shadow.detecter_chocs,
    )


def _rows_from_ledgers(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    return _rows_from_ledgers_impl(report)


def _independent_train_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    horizon_ms: int,
    shock_window_ms: float | None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    return _independent_train_rows_impl(
        rows,
        horizon_ms=horizon_ms,
        shock_window_ms=shock_window_ms,
    )


def _score_report(
    report: Mapping[str, Any],
    *,
    coin: str,
    threshold_bps: float,
    horizon_ms: int,
    trial_count: int,
    mechanism: str = MECHANISM,
    direction_multiplier: int = 1,
    min_train_fills: int = MIN_TRAIN_FILLS,
    shock_window_ms: float | None = None,
    admission_policy: str = ADMISSION_PRIOR_MEAN_POSITIVE,
    economic_predeclaration_id: str | None = None,
) -> dict[str, Any]:
    return _score_report_impl(
        report,
        coin=coin,
        threshold_bps=threshold_bps,
        horizon_ms=horizon_ms,
        trial_count=trial_count,
        mechanism=mechanism,
        direction_multiplier=direction_multiplier,
        min_train_fills=min_train_fills,
        shock_window_ms=shock_window_ms,
        admission_policy=admission_policy,
        economic_predeclaration_id=economic_predeclaration_id,
        family_alpha=FAMILY_ALPHA,
        diagnostic_only_threshold_bps=DIAGNOSTIC_ONLY_SHOCK_THRESHOLD_BPS,
        min_distinct_days=MIN_DISTINCT_DAYS,
        max_top_positive_share=MAX_TOP_POSITIVE_SHARE,
        rows_loader=_rows_from_ledgers,
        independence_filter=_independent_train_rows,
        summarizer=summarize_train_rows,
    )


def explore_lead_lag_multiasset_train(
    root: str | Path,
    lead_sources: Sequence[str | Path],
    *,
    candidate_coins: Sequence[str] = DEFAULT_CANDIDATE_COINS,
) -> dict[str, Any]:
    """Explore the fixed grid without loading the chronological heldout span."""

    tape, tape_meta = load_multiasset_train_tape(root, lead_sources, coins=candidate_coins)
    l2_history = {
        coin: list(streams.get("HL_BOOK") or []) for coin, streams in tape.items() if streams.get("HL_BOOK")
    }
    missing_book_tape = {coin: streams for coin, streams in tape.items() if coin not in l2_history}
    fallback_meta: dict[str, Any] | None = None
    if missing_book_tape:
        fallback_history, _public_trades, fallback_meta = load_market_microstructure_event_windows(
            root,
            _shock_timestamps(missing_book_tape),
            before_ms=1_000,
            after_ms=max(
                int(horizon) for hypothesis in TRAIN_HYPOTHESES for horizon in hypothesis["horizons_ms"]
            )
            + 2_000,
        )
        for coin, rows in fallback_history.items():
            if rows:
                l2_history[str(coin).upper()] = list(rows)
    l2_meta = {
        "schema_version": "hypersmart.lead_lag_multiasset_books.v1",
        "primary_source": "ALIGNED_BBO_SAME_SHARD_CAUSAL",
        "same_shard_rows": sum(len(streams.get("HL_BOOK") or []) for streams in tape.values()),
        "same_shard_coins": sorted(coin for coin, streams in tape.items() if streams.get("HL_BOOK")),
        "fallback_requested_coins": sorted(missing_book_tape),
        "fallback": fallback_meta,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_loaded": False,
        "paper_read_only": True,
        "real_execution": False,
    }
    latency = load_runtime_latency_evidence(root)
    variants: list[dict[str, Any]] = []
    shock_cache: dict[tuple[str, float, float | None], list[tuple[int, float]]] = {}
    for coin in candidate_coins:
        selected_coin = str(coin).upper()
        streams = tape.get(selected_coin)
        if not streams:
            continue
        trades = list(streams.get("TRADE") or [])
        for hypothesis in TRAIN_HYPOTHESES:
            for shock_window_ms in hypothesis["shock_windows_ms"]:
                for threshold in hypothesis["shock_thresholds_bps"]:
                    key = (
                        selected_coin,
                        float(threshold),
                        (float(shock_window_ms) if shock_window_ms is not None else None),
                    )
                    if key in shock_cache:
                        continue
                    shock_cache[key] = (
                        lead_lag_shadow.detecter_chocs(
                            trades,
                            seuil_bps=float(threshold),
                        )
                        if shock_window_ms is None
                        else lead_lag_shadow.detecter_chocs_fenetre(
                            trades,
                            seuil_bps=float(threshold),
                            fenetre_ms=float(shock_window_ms),
                        )
                    )
    planned_cross_pairs = _planned_cross_asset_pairs(candidate_coins)
    for leader in sorted({pair[0] for pair in planned_cross_pairs}):
        streams = tape.get(leader)
        if not streams:
            continue
        trades = list(streams.get("TRADE") or [])
        for shock_window_ms in CROSS_ASSET_SHOCK_WINDOWS_MS:
            for threshold in CROSS_ASSET_SHOCK_THRESHOLDS_BPS:
                key = (leader, float(threshold), float(shock_window_ms))
                if key not in shock_cache:
                    shock_cache[key] = lead_lag_shadow.detecter_chocs_fenetre(
                        trades,
                        seuil_bps=float(threshold),
                        fenetre_ms=float(shock_window_ms),
                    )
    combinations_per_coin = sum(
        len(hypothesis["shock_thresholds_bps"])
        * len(hypothesis["horizons_ms"])
        * len(hypothesis["shock_windows_ms"])
        for hypothesis in TRAIN_HYPOTHESES
    )
    cross_combinations_per_pair = len(CROSS_ASSET_SHOCK_THRESHOLDS_BPS) * len(CROSS_ASSET_HORIZONS_MS) * len(CROSS_ASSET_SHOCK_WINDOWS_MS)
    base_trial_count = max(
        1,
        len(candidate_coins) * combinations_per_coin + len(planned_cross_pairs) * cross_combinations_per_pair,
    )
    book_confirmation_trials = book_confirmation_trial_count(len(candidate_coins))
    trial_count = (
        research_family_trial_count(base_trial_count, len(planned_cross_pairs))
        + book_confirmation_trials
    )
    for hypothesis in TRAIN_HYPOTHESES:
        for coin in candidate_coins:
            selected_coin = str(coin).upper()
            if selected_coin not in tape:
                continue
            for shock_window_ms in hypothesis["shock_windows_ms"]:
                for threshold in hypothesis["shock_thresholds_bps"]:
                    for horizon in hypothesis["horizons_ms"]:
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
                            direction_multiplier=int(hypothesis["direction_multiplier"]),
                            shock_window_ms=(float(shock_window_ms) if shock_window_ms is not None else None),
                            admission_policy=str(hypothesis["admission_policy"]),
                            precomputed_shocks={
                                selected_coin: shock_cache[
                                    (
                                        selected_coin,
                                        float(threshold),
                                        (float(shock_window_ms) if shock_window_ms is not None else None),
                                    )
                                ]
                            },
                            inputs_sorted=True,
                        )
                        variants.append(
                            _score_report(
                                report,
                                coin=selected_coin,
                                threshold_bps=float(threshold),
                                horizon_ms=int(horizon),
                                trial_count=trial_count,
                                mechanism=str(hypothesis["mechanism"]),
                                direction_multiplier=int(hypothesis["direction_multiplier"]),
                                min_train_fills=int(hypothesis["min_train_fills"]),
                                shock_window_ms=(
                                    float(shock_window_ms) if shock_window_ms is not None else None
                                ),
                                admission_policy=str(hypothesis["admission_policy"]),
                            )
                        )
    book_confirmation_cache: dict[
        tuple[str, float, float, float], tuple[list[tuple[int, float]], dict[str, Any]]
    ] = {}
    for coin in candidate_coins:
        selected_coin = str(coin).upper()
        streams = tape.get(selected_coin)
        if not streams:
            continue
        trades = list(streams.get("TRADE") or [])
        trade_observations = list(streams.get("TRADE_OBS") or [])
        follower_books = list(l2_history.get(selected_coin, ()))
        if not trades or not trade_observations or not follower_books:
            continue
        aligned_source_ids = sorted(
            set(streams.get("TRADE_SOURCE_IDS") or ())
            & set(streams.get("HL_BOOK_SOURCE_IDS") or ())
        )
        if not aligned_source_ids:
            continue
        for shock_window_ms in BOOK_CONFIRMATION_SHOCK_WINDOWS_MS:
            for threshold in BOOK_CONFIRMATION_SHOCK_THRESHOLDS_BPS:
                shock_key = (selected_coin, float(threshold), float(shock_window_ms))
                if shock_key not in shock_cache:
                    shock_cache[shock_key] = lead_lag_shadow.detecter_chocs_fenetre(
                        trades,
                        seuil_bps=float(threshold),
                        fenetre_ms=float(shock_window_ms),
                    )
                raw_shocks = shock_cache[shock_key]
                for imbalance_threshold in BOOK_CONFIRMATION_IMBALANCE_THRESHOLDS:
                    confirmation_key = (
                        selected_coin,
                        float(threshold),
                        float(shock_window_ms),
                        float(imbalance_threshold),
                    )
                    confirmed_shocks, confirmation_diagnostics = (
                        confirm_shocks_with_causal_book(
                            raw_shocks,
                            follower_books,
                            trade_observations,
                            min_abs_imbalance=float(imbalance_threshold),
                            max_book_age_ms=BOOK_CONFIRMATION_MAX_BOOK_AGE_MS,
                        )
                    )
                    book_confirmation_cache[confirmation_key] = (
                        confirmed_shocks,
                        confirmation_diagnostics,
                    )
                    for horizon in BOOK_CONFIRMATION_HORIZONS_MS:
                        report = replay_measured_lead_lag(
                            {selected_coin: streams},
                            {selected_coin: follower_books},
                            shock_threshold_bps=float(threshold),
                            horizon_ms=int(horizon),
                            latency_evidence=latency,
                            notional_usd=NOTIONAL_USD,
                            min_history=5,
                            min_expected_net_bps=0.0,
                            min_episodes=1,
                            direction_multiplier=1,
                            shock_window_ms=float(shock_window_ms),
                            admission_policy=ADMISSION_PREDECLARED_ALL_SIGNALS,
                            precomputed_shocks={selected_coin: confirmed_shocks},
                            inputs_sorted=True,
                        )
                        scored = _score_report(
                            report,
                            coin=selected_coin,
                            threshold_bps=float(threshold),
                            horizon_ms=int(horizon),
                            trial_count=trial_count,
                            mechanism=BOOK_CONFIRMATION_MECHANISM,
                            direction_multiplier=1,
                            min_train_fills=BOOK_CONFIRMATION_MIN_TRAIN_FILLS,
                            shock_window_ms=float(shock_window_ms),
                            admission_policy=ADMISSION_PREDECLARED_ALL_SIGNALS,
                        )
                        scored.update(
                            {
                                "direction_policy": "EXTERNAL_SHOCK_BOOK_IMBALANCE_AGREEMENT",
                                "book_imbalance_threshold": float(imbalance_threshold),
                                "max_confirmation_book_age_ms": BOOK_CONFIRMATION_MAX_BOOK_AGE_MS,
                                "book_confirmation_diagnostics": dict(
                                    confirmation_diagnostics
                                ),
                                "aligned_source_ids": aligned_source_ids,
                            }
                        )
                        variants.append(scored)
    for leader, follower in planned_cross_pairs:
        leader_streams, follower_streams = tape.get(leader), tape.get(follower)
        if not leader_streams or not follower_streams:
            continue
        if not (follower_books := list(follower_streams.get("HL_BOOK") or [])):
            continue
        shared_sources = sorted(set(leader_streams.get("TRADE_SOURCE_IDS") or ()) & set(follower_streams.get("HL_BOOK_SOURCE_IDS") or ()))
        if not shared_sources:
            continue
        synthetic_tape = {
            follower: {
                "HL": [],
                "BIN": [],
                "TRADE": list(leader_streams.get("TRADE") or []),
            }
        }
        for shock_window_ms in CROSS_ASSET_SHOCK_WINDOWS_MS:
            for threshold in CROSS_ASSET_SHOCK_THRESHOLDS_BPS:
                shocks = shock_cache.get(
                    (leader, float(threshold), float(shock_window_ms)),
                    [],
                )
                for horizon in CROSS_ASSET_HORIZONS_MS:
                    report = replay_measured_lead_lag(
                        synthetic_tape,
                        {follower: follower_books},
                        shock_threshold_bps=float(threshold),
                        horizon_ms=int(horizon),
                        latency_evidence=latency,
                        notional_usd=NOTIONAL_USD,
                        min_history=5,
                        min_expected_net_bps=0.0,
                        min_episodes=1,
                        direction_multiplier=1,
                        shock_window_ms=float(shock_window_ms),
                        admission_policy=ADMISSION_PREDECLARED_ALL_SIGNALS,
                        precomputed_shocks={follower: shocks},
                        inputs_sorted=True,
                    )
                    scored = _score_report(
                        report,
                        coin=follower,
                        threshold_bps=float(threshold),
                        horizon_ms=int(horizon),
                        trial_count=trial_count,
                        mechanism=CROSS_ASSET_MECHANISM,
                        direction_multiplier=1,
                        min_train_fills=CROSS_ASSET_MIN_TRAIN_FILLS,
                        shock_window_ms=float(shock_window_ms),
                        admission_policy=ADMISSION_PREDECLARED_ALL_SIGNALS,
                    )
                    scored.update(
                        {
                            "leader_coin": leader,
                            "follower_coin": follower,
                            "aligned_source_ids": shared_sources,
                            "direction_policy": "CROSS_ASSET_MAJOR_TO_ALT_CONTINUATION",
                        }
                    )
                    variants.append(scored)
    for leader, follower in planned_cross_pairs:
        leader_streams, follower_streams = tape.get(leader), tape.get(follower)
        if not leader_streams or not follower_streams:
            continue
        shared_sources = sorted(
            set(leader_streams.get("TRADE_SOURCE_IDS") or ())
            & set(follower_streams.get("TRADE_SOURCE_IDS") or ())
            & set(follower_streams.get("HL_BOOK_SOURCE_IDS") or ())
        )
        if not shared_sources:
            continue
        source_id = shared_sources[0]
        reference_rows = [
            dict(row)
            for row in (leader_streams.get("TRADE_OBS") or [])
            if str(row.get("source_id") or "") == source_id
        ]
        follower_rows = [
            dict(row)
            for row in (follower_streams.get("TRADE_OBS") or [])
            if str(row.get("source_id") or "") == source_id
        ]
        follower_books = [
            dict(row)
            for row in (follower_streams.get("HL_BOOK") or [])
            if str(row.get("source_id") or "") == source_id
        ]
        if not reference_rows or not follower_rows or not follower_books:
            continue
        residual_tape = {
            follower: {
                "HL": [],
                "BIN": [],
                "TRADE": list(follower_streams.get("TRADE") or []),
            }
        }
        for beta in REFERENCE_RESIDUAL_BETAS:
            for shock_window_ms in REFERENCE_RESIDUAL_WINDOWS_MS:
                for threshold in REFERENCE_RESIDUAL_THRESHOLDS_BPS:
                    shocks, residual_diagnostics = detect_reference_residual_shocks(
                        reference_rows,
                        follower_rows,
                        window_ms=int(shock_window_ms),
                        threshold_bps=float(threshold),
                        beta=float(beta),
                        beta_asof_ms=0,
                    )
                    for direction_policy, direction_multiplier in REFERENCE_RESIDUAL_DIRECTION_POLICIES:
                        for horizon in REFERENCE_RESIDUAL_HORIZONS_MS:
                            report = replay_measured_lead_lag(
                                residual_tape,
                                {follower: follower_books},
                                shock_threshold_bps=float(threshold),
                                horizon_ms=int(horizon),
                                latency_evidence=latency,
                                notional_usd=NOTIONAL_USD,
                                min_history=5,
                                min_expected_net_bps=0.0,
                                min_episodes=1,
                                direction_multiplier=int(direction_multiplier),
                                shock_window_ms=float(shock_window_ms),
                                admission_policy=ADMISSION_PREDECLARED_ALL_SIGNALS,
                                precomputed_shocks={follower: shocks},
                                inputs_sorted=True,
                            )
                            scored = _score_report(
                                report,
                                coin=follower,
                                threshold_bps=float(threshold),
                                horizon_ms=int(horizon),
                                trial_count=trial_count,
                                mechanism=REFERENCE_RESIDUAL_MECHANISM,
                                direction_multiplier=int(direction_multiplier),
                                min_train_fills=REFERENCE_RESIDUAL_MIN_TRAIN_FILLS,
                                shock_window_ms=float(shock_window_ms),
                                admission_policy=ADMISSION_PREDECLARED_ALL_SIGNALS,
                            )
                            scored.update(
                                {
                                    "leader_coin": leader,
                                    "follower_coin": follower,
                                    "aligned_source_ids": [source_id],
                                    "direction_policy": str(direction_policy),
                                    "reference_beta": float(beta),
                                    "reference_beta_asof_ms": 0,
                                    "reference_residual_diagnostics": dict(residual_diagnostics),
                                }
                            )
                            variants.append(scored)
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
            "mechanism": selected["mechanism"],
            "direction_multiplier": selected["direction_multiplier"],
            "direction_policy": selected["direction_policy"],
            "coin": selected["coin"],
            "leader_coin": selected.get("leader_coin"),
            "follower_coin": selected.get("follower_coin"),
            "aligned_source_ids": selected.get("aligned_source_ids"),
            "reference_beta": selected.get("reference_beta"),
            "reference_beta_asof_ms": selected.get("reference_beta_asof_ms"),
            "book_imbalance_threshold": selected.get("book_imbalance_threshold"),
            "max_confirmation_book_age_ms": selected.get(
                "max_confirmation_book_age_ms"
            ),
            "shock_threshold_bps": selected["shock_threshold_bps"],
            "horizon_ms": selected["horizon_ms"],
            "shock_window_ms": selected["shock_window_ms"],
            "admission_policy": selected["admission_policy"],
            "notional_usd": NOTIONAL_USD,
            "candidate_universe": list(DEFAULT_CANDIDATE_COINS),
            "research_family_trial_count": trial_count,
            "minimum_train_fills": selected["minimum_train_fills"],
            "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        }
        if selected is not None
        else None
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "mechanism": "lead_lag_multi_hypothesis_train_only",
        "status": "TRAIN_ELIGIBLE_TO_FREEZE" if selected else "NO_ROBUST_TRAIN_CANDIDATE",
        "selection_eligible": selected is not None,
        "physical_freeze_allowed": selected is not None,
        "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
        "heldout_evaluated": False,
        "candidate_universe": list(DEFAULT_CANDIDATE_COINS),
        "fixed_grid": {
            "notional_usd": NOTIONAL_USD,
            "trial_count": trial_count,
            "hypotheses": [
                {
                    "mechanism": str(hypothesis["mechanism"]),
                    "direction_multiplier": int(hypothesis["direction_multiplier"]),
                    "direction_policy": str(hypothesis["direction_policy"]),
                    "shock_thresholds_bps": list(hypothesis["shock_thresholds_bps"]),
                    "horizons_ms": list(hypothesis["horizons_ms"]),
                    "shock_windows_ms": list(hypothesis["shock_windows_ms"]),
                    "admission_policy": str(hypothesis["admission_policy"]),
                    "minimum_train_fills": int(hypothesis["min_train_fills"]),
                }
                for hypothesis in TRAIN_HYPOTHESES
            ],
            "cross_asset_hypothesis": {
                "mechanism": CROSS_ASSET_MECHANISM,
                "direction_multiplier": 1,
                "direction_policy": "CROSS_ASSET_MAJOR_TO_ALT_CONTINUATION",
                "leaders": list(CROSS_ASSET_LEADERS),
                "followers": list(CROSS_ASSET_FOLLOWERS),
                "planned_pairs": [list(pair) for pair in planned_cross_pairs],
                "shock_thresholds_bps": list(CROSS_ASSET_SHOCK_THRESHOLDS_BPS),
                "horizons_ms": list(CROSS_ASSET_HORIZONS_MS),
                "shock_windows_ms": list(CROSS_ASSET_SHOCK_WINDOWS_MS),
                "admission_policy": ADMISSION_PREDECLARED_ALL_SIGNALS,
                "minimum_train_fills": CROSS_ASSET_MIN_TRAIN_FILLS,
            },
            "reference_residual_hypothesis": {
                "mechanism": REFERENCE_RESIDUAL_MECHANISM,
                "planned_pairs": [list(pair) for pair in planned_cross_pairs],
                "betas": list(REFERENCE_RESIDUAL_BETAS),
                "direction_policies": [policy for policy, _multiplier in REFERENCE_RESIDUAL_DIRECTION_POLICIES],
                "shock_thresholds_bps": list(REFERENCE_RESIDUAL_THRESHOLDS_BPS),
                "horizons_ms": list(REFERENCE_RESIDUAL_HORIZONS_MS),
                "shock_windows_ms": list(REFERENCE_RESIDUAL_WINDOWS_MS),
                "admission_policy": ADMISSION_PREDECLARED_ALL_SIGNALS,
                "minimum_train_fills": REFERENCE_RESIDUAL_MIN_TRAIN_FILLS,
                "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
            },
            "book_confirmation_hypothesis": {
                "mechanism": BOOK_CONFIRMATION_MECHANISM,
                "direction_multiplier": 1,
                "direction_policy": "EXTERNAL_SHOCK_BOOK_IMBALANCE_AGREEMENT",
                "shock_thresholds_bps": list(BOOK_CONFIRMATION_SHOCK_THRESHOLDS_BPS),
                "horizons_ms": list(BOOK_CONFIRMATION_HORIZONS_MS),
                "shock_windows_ms": list(BOOK_CONFIRMATION_SHOCK_WINDOWS_MS),
                "book_imbalance_thresholds": list(
                    BOOK_CONFIRMATION_IMBALANCE_THRESHOLDS
                ),
                "max_confirmation_book_age_ms": BOOK_CONFIRMATION_MAX_BOOK_AGE_MS,
                "admission_policy": ADMISSION_PREDECLARED_ALL_SIGNALS,
                "minimum_train_fills": BOOK_CONFIRMATION_MIN_TRAIN_FILLS,
                "trial_count": book_confirmation_trials,
                "selection_scope": "TRAIN_ONLY_PRE_FREEZE",
            },
        },
        "selected": selected,
        "freeze_candidate": freeze_payload,
        "freeze_candidate_sha256": stable_hash(freeze_payload) if freeze_payload else None,
        "variants": variants,
        "train_tape": tape_meta,
        "microstructure": l2_meta,
        "latency_evidence": latency,
        "shock_detection_cache": {
            "unique_definitions": len(shock_cache),
            "signals_by_definition": {
                f"{coin}|{threshold:g}|{window if window is not None else 'consecutive'}": len(rows)
                for (coin, threshold, window), rows in shock_cache.items()
            },
            "reused_across_horizons": True,
        },
        "book_confirmation_cache": {
            "unique_definitions": len(book_confirmation_cache),
            "reused_across_horizons": True,
        },
        "paper_read_only": True,
        "real_execution": False,
    }


__all__ = ["CROSS_ASSET_FOLLOWERS", "CROSS_ASSET_HORIZONS_MS", "CROSS_ASSET_LEADERS", "CROSS_ASSET_MECHANISM", "CROSS_ASSET_MIN_TRAIN_FILLS", "CROSS_ASSET_SHOCK_THRESHOLDS_BPS", "CROSS_ASSET_SHOCK_WINDOWS_MS", "DEFAULT_CANDIDATE_COINS", "DIAGNOSTIC_ONLY_SHOCK_THRESHOLD_BPS", "EXTREME_REVERSAL_HORIZONS_MS", "EXTREME_REVERSAL_MECHANISM", "EXTREME_REVERSAL_MIN_TRAIN_FILLS", "EXTREME_REVERSAL_SHOCK_THRESHOLDS_BPS", "HORIZONS_MS", "MECHANISM", "SCHEMA_VERSION", "SHOCK_THRESHOLDS_BPS", "TRAIN_HYPOTHESES", "WINDOW_CONTINUATION_MECHANISM", "WINDOW_HORIZONS_MS", "WINDOW_MIN_TRAIN_FILLS", "WINDOW_SHOCK_THRESHOLDS_BPS", "WINDOW_SHOCK_WINDOWS_MS", "_independent_train_rows", "_planned_cross_asset_pairs", "_score_report", "explore_lead_lag_multiasset_train", "load_multiasset_train_tape"]
