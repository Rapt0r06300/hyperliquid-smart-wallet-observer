"""Fail-closed replay and paper-decision controls for Copy-Vault."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) in {40, 64} and all(ch in "0123456789abcdefABCDEF" for ch in value)


def tape_contract_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require an explicit replay tape contract before a replay is planned."""
    if not rows:
        return _base("MORE_DATA", reason="empty_tape_contract")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("tape_id") or "").strip()
        or row.get("required_for_replay") is not True
        or not _hash(row.get("manifest_hash"))
        or row.get("safe") is not True
    ]
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="REPLAY_TAPE_CONTRACT_COMPLETE" if not invalid else "REPLAY_TAPE_CONTRACT_INCOMPLETE",
        tapes=len(rows),
        invalid_rows=invalid,
    )


def hotpath_replay_parity_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Compare hot-path and replay decisions on the same immutable input."""
    if not rows:
        return _base("MORE_DATA", reason="empty_hotpath_replay_parity")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not str(row.get("input_hash") or "").strip() or row.get("hotpath_decision") != row.get("replay_decision"):
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="HOTPATH_REPLAY_DECISION_PARITY" if not invalid else "HOTPATH_REPLAY_DECISION_MISMATCH",
        observations=len(rows),
        invalid_rows=invalid,
    )


def reconnect_receive_chrono_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require monotonic receive chronology and native identity across reconnects."""
    if not rows:
        return _base("MORE_DATA", reason="empty_reconnect_chronology")
    invalid: list[int] = []
    previous = -1
    for index, row in enumerate(rows):
        ts = row.get("receive_ts_ms") if isinstance(row, Mapping) else None
        if not isinstance(ts, int) or isinstance(ts, bool) or ts < previous or not str(row.get("native_event_id") or "").strip() if isinstance(row, Mapping) else True:
            invalid.append(index)
        else:
            previous = ts
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="RECONNECT_RECEIVE_CHRONOLOGY_VALID" if not invalid else "RECONNECT_RECEIVE_CHRONOLOGY_INVALID",
        observations=len(rows),
        invalid_rows=invalid,
    )


def sample_vs_real_capture_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reject a dataset that mixes sample and real capture in one source set."""
    if not rows:
        return _base("MORE_DATA", reason="empty_capture_inventory")
    by_dataset: dict[str, set[str]] = {}
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or row.get("capture_kind") not in {"sample", "real"} or not str(row.get("dataset_id") or "").strip():
            invalid.append(index)
            continue
        if row.get("capture_kind") == "real" and not str(row.get("provenance") or "").strip():
            invalid.append(index)
            continue
        by_dataset.setdefault(str(row["dataset_id"]), set()).add(str(row["capture_kind"]))
    mixed = sorted(dataset for dataset, kinds in by_dataset.items() if len(kinds) > 1)
    if invalid:
        return _base("UNMEASURABLE", reason="capture_identity_missing", invalid_rows=invalid)
    return _base(
        "PROVEN" if not mixed else "REJECTED",
        verdict="SAMPLE_AND_REAL_CAPTURE_SEPARATED" if not mixed else "SAMPLE_REAL_CAPTURE_MIXED",
        datasets=by_dataset,
        mixed_datasets=mixed,
    )


def observed_source_manifest_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Publish the source manifest used by a paper launch."""
    if not rows:
        return _base("MORE_DATA", reason="empty_observed_source_manifest")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("source") or "").strip()
        or not _hash(row.get("manifest_hash"))
        or not isinstance(row.get("observed_at_ms"), int)
    ]
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="OBSERVED_SOURCE_MANIFEST_PUBLISHED" if not invalid else "OBSERVED_SOURCE_MANIFEST_INCOMPLETE",
        sources=len(rows),
        invalid_rows=invalid,
    )


def paper_decision_engine_freeze_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Freeze engine version and code identity for every paper decision."""
    if not rows:
        return _base("MORE_DATA", reason="empty_paper_decisions")
    engines = {str(row.get("engine_version") or "") for row in rows if isinstance(row, Mapping)}
    hashes = {str(row.get("code_sha") or "") for row in rows if isinstance(row, Mapping)}
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not str(row.get("decision_id") or "").strip() or not str(row.get("engine_version") or "").strip() or not _hash(row.get("code_sha"))
    ]
    valid = not invalid and len(engines) == 1 and len(hashes) == 1
    return _base(
        "PROVEN" if valid else "UNMEASURABLE",
        verdict="PAPER_DECISION_ENGINE_FROZEN" if valid else "PAPER_DECISION_ENGINE_DRIFT",
        engine_versions=sorted(engines),
        code_shas=sorted(hashes),
        invalid_rows=invalid,
    )


def runtime_not_validated_dataset_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Prevent a live runtime directory from becoming a validated dataset."""
    if not isinstance(state, Mapping) or not isinstance(state.get("runtime_directory"), bool) or not isinstance(state.get("dataset_validated"), bool):
        return _base("UNMEASURABLE", reason="runtime_dataset_state_missing")
    valid = not (state["runtime_directory"] and state["dataset_validated"])
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="RUNTIME_DIRECTORY_NOT_DATASET" if valid else "RUNTIME_DIRECTORY_PROMOTED_TO_DATASET",
        runtime_directory=state["runtime_directory"],
        dataset_validated=state["dataset_validated"],
    )


def collect_analyze_phase_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Block ANALYZE while the canonical control plane is still collecting."""
    if not isinstance(state, Mapping) or not isinstance(state.get("phase"), str) or not isinstance(state.get("analyze_requested"), bool):
        return _base("UNMEASURABLE", reason="phase_request_state_missing")
    valid = state["phase"] != "COLLECT" or state["analyze_requested"] is False
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="ANALYZE_PHASE_BOUNDARY_RESPECTED" if valid else "ANALYZE_DURING_COLLECT_REJECTED",
        phase=state["phase"],
        analyze_requested=state["analyze_requested"],
    )


def replay_merge_order_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require deterministic seed and unique merge ordering for replay inputs."""
    if not rows:
        return _base("MORE_DATA", reason="empty_replay_merge")
    seeds = {row.get("seed") for row in rows if isinstance(row, Mapping)}
    orders = [row.get("merge_order") if isinstance(row, Mapping) else None for row in rows]
    valid = len(seeds) == 1 and next(iter(seeds), None) is not None and all(isinstance(order, int) and not isinstance(order, bool) for order in orders) and len(orders) == len(set(orders))
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="REPLAY_MERGE_ORDER_DETERMINISTIC" if valid else "REPLAY_MERGE_ORDER_INVALID",
        seeds=sorted(str(seed) for seed in seeds),
        merge_orders=orders,
    )


def oos_forward_separation_receipt(rows: Sequence[Mapping[str, Any]], *, freeze_ts_ms: int) -> dict[str, Any]:
    """Keep OOS observations before the freeze and forward observations after it."""
    if not rows:
        return _base("MORE_DATA", reason="empty_oos_forward_rows")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        ts = row.get("ts_ms") if isinstance(row, Mapping) else None
        lane = row.get("lane") if isinstance(row, Mapping) else None
        if not isinstance(ts, int) or isinstance(ts, bool) or lane not in {"OOS", "FORWARD"} or (lane == "OOS" and ts >= freeze_ts_ms) or (lane == "FORWARD" and ts < freeze_ts_ms):
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="OOS_FORWARD_SEPARATED" if not invalid else "OOS_FORWARD_MIXED",
        freeze_ts_ms=freeze_ts_ms,
        invalid_rows=invalid,
    )


def filesystem_order_receipt(paths: Sequence[str]) -> dict[str, Any]:
    """Require an explicit stable lexical order rather than filesystem order."""

    normalized = [str(path).replace("\\", "/") for path in paths]
    valid = bool(normalized) and len(normalized) == len(set(normalized)) and normalized == sorted(normalized)
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="FILESYSTEM_ORDER_EXPLICIT" if valid else "FILESYSTEM_ORDER_UNSAFE",
        order=normalized,
    )


def python_hash_seed_receipt(*, hash_seed: Any, hash_randomization_disabled: bool) -> dict[str, Any]:
    """Require a declared deterministic hash seed for replay."""

    valid = isinstance(hash_seed, int) and not isinstance(hash_seed, bool) and hash_seed >= 0 and bool(hash_randomization_disabled)
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="PYTHON_HASH_SEED_PINNED" if valid else "PYTHON_HASH_SEED_UNPINNED",
        hash_seed=hash_seed if valid else None,
    )


def utc_timezone_receipt(*, timezone_name: Any, timestamps_utc: bool) -> dict[str, Any]:
    """Replay timestamps must be explicitly normalized to UTC."""

    valid = str(timezone_name).strip().upper() == "UTC" and bool(timestamps_utc)
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="REPLAY_TIMEZONE_UTC" if valid else "REPLAY_TIMEZONE_UNSAFE",
        timezone="UTC" if valid else None,
    )


def decision_data_causality_receipt(
    *, data_ts_ms: Any, decision_ts_ms: Any, observed_before_decision: bool
) -> dict[str, Any]:
    """Data obtained after a decision cannot influence that decision."""

    valid = (
        isinstance(data_ts_ms, int)
        and not isinstance(data_ts_ms, bool)
        and isinstance(decision_ts_ms, int)
        and not isinstance(decision_ts_ms, bool)
        and data_ts_ms <= decision_ts_ms
        and bool(observed_before_decision)
    )
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="DECISION_DATA_CAUSAL" if valid else "DECISION_DATA_LOOKAHEAD",
        data_ts_ms=data_ts_ms if valid else None,
        decision_ts_ms=decision_ts_ms if valid else None,
    )


def complete_shard_set_receipt(
    *, required_shards: Sequence[str], present_shards: Sequence[str]
) -> dict[str, Any]:
    """A replay must reject a missing required shard instead of skipping it."""

    required = {str(shard) for shard in required_shards if str(shard).strip()}
    present = {str(shard) for shard in present_shards if str(shard).strip()}
    missing = sorted(required - present)
    valid = bool(required) and not missing and present <= required
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="REPLAY_SHARDS_COMPLETE" if valid else "REPLAY_SHARD_MISSING",
        missing_shards=missing,
    )


def publication_epoch_receipt(rows: Sequence[Mapping[str, Any]], *, expected_epoch: Any) -> dict[str, Any]:
    """Do not mix observations from different publication epochs."""

    invalid = [
        index
        for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or row.get("publication_epoch") != expected_epoch
    ]
    valid = bool(rows) and not invalid and expected_epoch is not None
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="REPLAY_EPOCH_ALIGNED" if valid else "REPLAY_EPOCH_MIXED",
        expected_epoch=expected_epoch if valid else None,
        invalid_rows=invalid,
    )


def complete_segment_receipt(*, segment_complete: bool, partial_explicit: bool) -> dict[str, Any]:
    """Explicitly partial segments are never silently admitted to replay."""

    valid = bool(segment_complete) and not bool(partial_explicit)
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="REPLAY_SEGMENT_COMPLETE" if valid else "REPLAY_SEGMENT_PARTIAL",
        segment_complete=bool(segment_complete),
    )


def reconstructed_bbo_receipt(
    *, bid: Any, ask: Any, source_level_count: Any, reconstructed: bool
) -> dict[str, Any]:
    """A BBO is valid only when reconstructed from observed source levels."""

    finite = all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in (bid, ask))
    valid = finite and float(bid) > 0.0 and float(ask) > float(bid) and isinstance(source_level_count, int) and source_level_count > 0 and bool(reconstructed)
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="BBO_RECONSTRUCTED" if valid else "BBO_UNRECONSTRUCTED",
        bid=float(bid) if finite else None,
        ask=float(ask) if finite else None,
    )


def negotiable_tick_receipt(*, price: Any, tick_size: Any, tradeable: bool) -> dict[str, Any]:
    """Reject fills on non-positive, non-aligned or explicitly non-tradeable ticks."""

    finite = all(isinstance(value, (int, float)) and math.isfinite(float(value)) for value in (price, tick_size))
    aligned = finite and float(tick_size) > 0.0 and abs((float(price) / float(tick_size)) - round(float(price) / float(tick_size))) <= 1e-9
    valid = aligned and float(price) > 0.0 and bool(tradeable)
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="TICK_NEGOTIABLE" if valid else "TICK_NON_NEGOTIABLE",
        price=float(price) if finite else None,
        tick_size=float(tick_size) if finite else None,
    )


def future_book_access_receipt(
    *, book_ts_ms: Any, visible_ts_ms: Any, decision_ts_ms: Any
) -> dict[str, Any]:
    """The replay may use only a book visible no later than the decision."""

    values = (book_ts_ms, visible_ts_ms, decision_ts_ms)
    valid = all(isinstance(value, int) and not isinstance(value, bool) for value in values)
    if valid:
        valid = book_ts_ms <= visible_ts_ms <= decision_ts_ms
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="BOOK_POINT_IN_TIME" if valid else "BOOK_LOOKAHEAD_REJECTED",
        book_ts_ms=book_ts_ms if valid else None,
        visible_ts_ms=visible_ts_ms if valid else None,
        decision_ts_ms=decision_ts_ms if valid else None,
    )


def engine_parity_receipt(*, fast_engine_hash: Any, precise_engine_hash: Any, input_hash: Any) -> dict[str, Any]:
    """A fast replay is admissible only when it is equivalent on frozen input."""

    valid = bool(str(input_hash).strip()) and str(fast_engine_hash).strip() == str(precise_engine_hash).strip()
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="FAST_PRECISE_PARITY" if valid else "FAST_PRECISE_MISMATCH",
        input_hash=str(input_hash) if valid else None,
    )


def fee_config_freeze_receipt(*, replay_config_hash: Any, current_config_hash: Any) -> dict[str, Any]:
    """Replay fees must come from the frozen replay configuration, not live config."""

    valid = bool(str(replay_config_hash).strip()) and str(replay_config_hash) == str(current_config_hash)
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="REPLAY_FEE_CONFIG_FROZEN" if valid else "REPLAY_FEE_CONFIG_DRIFT",
        config_hash=str(replay_config_hash) if valid else None,
    )


def checkpoint_boundary_receipt(*, boundary_event_included: bool, next_event_is_after_boundary: bool) -> dict[str, Any]:
    """Checkpoint resume must preserve the exact boundary event."""

    valid = bool(boundary_event_included) and bool(next_event_is_after_boundary)
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="CHECKPOINT_BOUNDARY_PRESERVED" if valid else "CHECKPOINT_BOUNDARY_SKIPPED",
        boundary_preserved=valid,
    )


def checkpoint_dedup_receipt(*, checkpoint_event_id: Any, replayed_event_ids: Sequence[Any]) -> dict[str, Any]:
    """Resume must not replay the event already committed by the checkpoint."""

    replayed = {str(event_id) for event_id in replayed_event_ids}
    valid = bool(str(checkpoint_event_id).strip()) and str(checkpoint_event_id) not in replayed
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="CHECKPOINT_DEDUPLICATED" if valid else "CHECKPOINT_EVENT_REPLAYED",
        replayed_event_ids=sorted(replayed),
    )


def dataset_pnl_stability_receipt(*, input_hashes: Sequence[Any], pnl_values: Sequence[Any]) -> dict[str, Any]:
    """Identical frozen inputs must produce one deterministic PnL."""

    hashes = [str(value).strip() for value in input_hashes]
    values = list(pnl_values)
    valid = bool(hashes) and len(hashes) == len(values) and len(set(hashes)) == 1 and len(set(map(str, values))) == 1
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="REPLAY_PNL_STABLE" if valid else "REPLAY_PNL_NON_DETERMINISTIC",
        runs=len(values),
    )


def event_hash_collision_receipt(*, event_hashes: Sequence[Any], native_event_ids: Sequence[Any]) -> dict[str, Any]:
    """Do not collapse distinct native events behind a colliding replay hash."""

    hashes = [str(value).strip() for value in event_hashes]
    ids = [str(value).strip() for value in native_event_ids]
    valid = bool(hashes) and len(hashes) == len(ids) and all(hashes) and all(ids) and len(set(hashes)) == len(hashes)
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="EVENT_HASHES_UNIQUE" if valid else "EVENT_HASH_COLLISION",
        events=len(hashes),
    )


def shard_order_preservation_receipt(*, source_event_ids: Sequence[Any], decompressed_event_ids: Sequence[Any]) -> dict[str, Any]:
    """Compression/decompression must preserve the logical event order exactly."""

    source = [str(value) for value in source_event_ids]
    decompressed = [str(value) for value in decompressed_event_ids]
    valid = bool(source) and source == decompressed and len(source) == len(set(source))
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="SHARD_ORDER_PRESERVED" if valid else "SHARD_ORDER_MUTATED",
        events=len(source),
    )


def thread_count_determinism_receipt(*, outputs_by_thread_count: Mapping[Any, Any]) -> dict[str, Any]:
    """Changing worker count must not change the frozen replay output."""

    values = list(outputs_by_thread_count.values())
    valid = bool(values) and len({repr(value) for value in values}) == 1
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="THREAD_COUNT_DETERMINISTIC" if valid else "THREAD_COUNT_NON_DETERMINISTIC",
        thread_counts=len(values),
    )


def refusal_reason_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Every replay refusal must retain a non-empty machine-readable reason."""

    invalid = [
        index
        for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("refused") is not True
        or not str(row.get("reason") or "").strip()
    ]
    valid = bool(rows) and not invalid
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="REFUSAL_REASONS_PRESERVED" if valid else "REFUSAL_REASON_MISSING",
        invalid_rows=invalid,
    )


def liquidatable_exposure_receipt(
    *, exposure_usd: Any, available_exit_liquidity_usd: Any, observed_book: bool
) -> dict[str, Any]:
    """A replay cannot finish with exposure larger than observed exit liquidity."""

    try:
        exposure = float(exposure_usd)
        liquidity = float(available_exit_liquidity_usd)
        valid = math.isfinite(exposure) and math.isfinite(liquidity) and exposure >= 0.0 and liquidity >= exposure and bool(observed_book)
    except (TypeError, ValueError, OverflowError):
        exposure = liquidity = None
        valid = False
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="EXPOSURE_LIQUIDATABLE" if valid else "EXPOSURE_NOT_LIQUIDATABLE",
        exposure_usd=exposure if valid else None,
        available_exit_liquidity_usd=liquidity if valid else None,
    )


def oos_selection_timing_receipt(*, selection_ts_ms: Any, outcome_ts_ms: Any, oos_start_ts_ms: Any) -> dict[str, Any]:
    """Selection must be frozen before outcome observation and OOS start."""

    valid = all(isinstance(value, int) and not isinstance(value, bool) for value in (selection_ts_ms, outcome_ts_ms, oos_start_ts_ms)) and selection_ts_ms < outcome_ts_ms and selection_ts_ms <= oos_start_ts_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="OOS_SELECTION_PRE_OUTCOME" if valid else "OOS_SELECTION_LOOKAHEAD", selection_ts_ms=selection_ts_ms, outcome_ts_ms=outcome_ts_ms, oos_start_ts_ms=oos_start_ts_ms, fail_closed=not valid)


def purged_window_receipt(*, train_intervals: Sequence[Sequence[Any]], test_intervals: Sequence[Sequence[Any]], horizon_ms: Any) -> dict[str, Any]:
    """Train observations must be purged far enough from every test horizon."""

    valid = isinstance(horizon_ms, int) and not isinstance(horizon_ms, bool) and horizon_ms >= 0
    overlaps: list[tuple[int, int]] = []
    if valid:
        for train_index, train in enumerate(train_intervals):
            if len(train) != 2 or not all(isinstance(value, int) and not isinstance(value, bool) for value in train):
                valid = False
                continue
            for test_index, test in enumerate(test_intervals):
                if len(test) != 2 or not all(isinstance(value, int) and not isinstance(value, bool) for value in test):
                    valid = False
                elif train[1] + horizon_ms > test[0] and test[1] >= train[0]:
                    overlaps.append((train_index, test_index))
        valid = valid and not overlaps
    return _base("PROVEN" if valid else "REJECTED", verdict="PURGED_WINDOWS_DISJOINT" if valid else "PURGED_WINDOWS_OVERLAP", overlaps=overlaps, fail_closed=not valid)


def leader_selection_receipt(*, leader_selection_ts_ms: Any, leader_observation_cutoff_ms: Any, pnl_cutoff_ms: Any) -> dict[str, Any]:
    """Leader selection must precede the observation and PnL cutoffs it uses."""

    valid = all(isinstance(value, int) and not isinstance(value, bool) for value in (leader_selection_ts_ms, leader_observation_cutoff_ms, pnl_cutoff_ms)) and leader_selection_ts_ms <= leader_observation_cutoff_ms <= pnl_cutoff_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="LEADER_SELECTION_CAUSAL" if valid else "LEADER_SELECTION_LOOKAHEAD", leader_selection_ts_ms=leader_selection_ts_ms, leader_observation_cutoff_ms=leader_observation_cutoff_ms, pnl_cutoff_ms=pnl_cutoff_ms, fail_closed=not valid)


def multiple_testing_receipt(*, trial_count: Any, correction_method: Any, adjusted_alpha: Any) -> dict[str, Any]:
    """A multi-trial claim requires an explicit correction and adjusted alpha."""

    try:
        alpha = float(adjusted_alpha)
        valid = isinstance(trial_count, int) and not isinstance(trial_count, bool) and trial_count > 0 and str(correction_method).strip().casefold() in {"bonferroni", "holm", "fdr"} and math.isfinite(alpha) and 0.0 < alpha <= 0.05
    except (TypeError, ValueError, OverflowError):
        alpha = None
        valid = False
    return _base("PROVEN" if valid else "REJECTED", verdict="MULTIPLE_TESTING_CORRECTED" if valid else "MULTIPLE_TESTING_UNCORRECTED", trial_count=trial_count, correction_method=correction_method, adjusted_alpha=alpha, fail_closed=not valid)


def champion_code_freeze_receipt(*, champion_sha: Any, evaluated_sha: Any, frozen: bool) -> dict[str, Any]:
    """The champion must retain the exact code identity used for evaluation."""

    valid = _hash(champion_sha) and _hash(evaluated_sha) and str(champion_sha).casefold() == str(evaluated_sha).casefold() and bool(frozen)
    return _base("PROVEN" if valid else "REJECTED", verdict="CHAMPION_CODE_FROZEN" if valid else "CHAMPION_CODE_MUTABLE", champion_sha=champion_sha, evaluated_sha=evaluated_sha, frozen=bool(frozen), fail_closed=not valid)


def champion_dataset_freeze_receipt(*, dataset_hash: Any, evaluated_dataset_hash: Any, frozen: bool) -> dict[str, Any]:
    """The champion must retain the exact dataset identity used for evaluation."""

    valid = _hash(dataset_hash) and _hash(evaluated_dataset_hash) and str(dataset_hash).casefold() == str(evaluated_dataset_hash).casefold() and bool(frozen)
    return _base("PROVEN" if valid else "REJECTED", verdict="CHAMPION_DATASET_FROZEN" if valid else "CHAMPION_DATASET_MUTABLE", dataset_hash=dataset_hash, evaluated_dataset_hash=evaluated_dataset_hash, frozen=bool(frozen), fail_closed=not valid)


def cost_model_freeze_receipt(*, cost_model_hash: Any, evaluated_cost_model_hash: Any, frozen: bool) -> dict[str, Any]:
    """The champion must retain the exact cost-model identity used for evaluation."""

    valid = _hash(cost_model_hash) and _hash(evaluated_cost_model_hash) and str(cost_model_hash).casefold() == str(evaluated_cost_model_hash).casefold() and bool(frozen)
    return _base("PROVEN" if valid else "REJECTED", verdict="CHAMPION_COST_MODEL_FROZEN" if valid else "CHAMPION_COST_MODEL_MUTABLE", cost_model_hash=cost_model_hash, evaluated_cost_model_hash=evaluated_cost_model_hash, frozen=bool(frozen), fail_closed=not valid)


def forward_maturity_receipt(*, freeze_ts_ms: Any, forward_end_ts_ms: Any, minimum_duration_ms: Any) -> dict[str, Any]:
    """Forward evidence must include a post-freeze maturity window."""

    valid = all(isinstance(value, int) and not isinstance(value, bool) for value in (freeze_ts_ms, forward_end_ts_ms, minimum_duration_ms)) and minimum_duration_ms > 0 and forward_end_ts_ms >= freeze_ts_ms + minimum_duration_ms
    return _base("PROVEN" if valid else "REJECTED", verdict="FORWARD_MATURITY_COMPLETE" if valid else "FORWARD_MATURITY_INCOMPLETE", freeze_ts_ms=freeze_ts_ms, forward_end_ts_ms=forward_end_ts_ms, minimum_duration_ms=minimum_duration_ms, fail_closed=not valid)


def wallet_disjointness_receipt(*, train_wallets: Sequence[Any], oos_wallets: Sequence[Any], overlap_analysis: bool) -> dict[str, Any]:
    """OOS wallet reuse requires an explicit overlap analysis."""

    train = {str(value) for value in train_wallets}
    oos = {str(value) for value in oos_wallets}
    overlap = sorted(train & oos)
    valid = bool(train) and bool(oos) and (not overlap or bool(overlap_analysis))
    return _base("PROVEN" if valid else "REJECTED", verdict="OOS_WALLET_BOUNDARY_EXPLICIT" if valid else "OOS_WALLET_REUSE_UNANALYZED", overlap=overlap, overlap_analysis=bool(overlap_analysis), fail_closed=not valid)


def holdout_hyperparam_receipt(*, tuning_cutoff_ms: Any, holdout_cutoff_ms: Any, tuned_after_holdout: bool) -> dict[str, Any]:
    """Hyperparameters must be frozen before the holdout is observed."""

    valid = isinstance(tuning_cutoff_ms, int) and not isinstance(tuning_cutoff_ms, bool) and isinstance(holdout_cutoff_ms, int) and not isinstance(holdout_cutoff_ms, bool) and tuning_cutoff_ms < holdout_cutoff_ms and not bool(tuned_after_holdout)
    return _base("PROVEN" if valid else "REJECTED", verdict="HOLDOUT_HYPERPARAMETER_FROZEN" if valid else "HOLDOUT_HYPERPARAMETER_LEAK", tuning_cutoff_ms=tuning_cutoff_ms, holdout_cutoff_ms=holdout_cutoff_ms, tuned_after_holdout=bool(tuned_after_holdout), fail_closed=not valid)


__all__ = [
    "tape_contract_receipt",
    "hotpath_replay_parity_receipt",
    "reconnect_receive_chrono_receipt",
    "sample_vs_real_capture_receipt",
    "observed_source_manifest_receipt",
    "paper_decision_engine_freeze_receipt",
    "runtime_not_validated_dataset_receipt",
    "collect_analyze_phase_receipt",
    "replay_merge_order_receipt",
    "oos_forward_separation_receipt",
    "filesystem_order_receipt",
    "python_hash_seed_receipt",
    "utc_timezone_receipt",
    "decision_data_causality_receipt",
    "complete_shard_set_receipt",
    "publication_epoch_receipt",
    "complete_segment_receipt",
    "reconstructed_bbo_receipt",
    "negotiable_tick_receipt",
    "future_book_access_receipt",
    "engine_parity_receipt",
    "fee_config_freeze_receipt",
    "checkpoint_boundary_receipt",
    "checkpoint_dedup_receipt",
    "dataset_pnl_stability_receipt",
    "event_hash_collision_receipt",
    "shard_order_preservation_receipt",
    "thread_count_determinism_receipt",
    "refusal_reason_receipt",
    "liquidatable_exposure_receipt",
    "oos_selection_timing_receipt",
    "purged_window_receipt",
    "leader_selection_receipt",
    "multiple_testing_receipt",
    "champion_code_freeze_receipt",
    "champion_dataset_freeze_receipt",
    "cost_model_freeze_receipt",
    "forward_maturity_receipt",
    "wallet_disjointness_receipt",
    "holdout_hyperparam_receipt",
]
