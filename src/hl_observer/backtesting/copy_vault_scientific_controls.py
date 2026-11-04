"""Fail-closed scientific controls for the Copy-Vault research lane.

These helpers validate evidence envelopes and replay partitions.  They never
invent a fill, PnL, coverage interval or economic certification, and they never
activate a strategy.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def independent_episode_receipt(
    rows: Sequence[Mapping[str, Any]],
    *,
    episode_field: str = "episode_id",
    fragment_field: str = "fragment_id",
) -> dict[str, Any]:
    """Count causal episodes instead of inflating evidence with fragments."""
    episodes: set[str] = set()
    fragments: set[str] = set()
    for row in rows or ():
        if not isinstance(row, Mapping):
            return _base("UNMEASURABLE", reason="invalid_row")
        episode = str(row.get(episode_field) or "").strip()
        fragment = str(row.get(fragment_field) or "").strip()
        if not episode or not fragment:
            return _base("UNMEASURABLE", reason="missing_episode_or_fragment")
        episodes.add(episode)
        fragments.add(fragment)
    if not episodes:
        return _base("MORE_DATA", reason="empty_sample")
    return _base(
        "PROVEN",
        verdict="INDEPENDENT_EPISODES_NOT_FRAGMENTS",
        independent_episode_count=len(episodes),
        fragment_count=len(fragments),
    )


def forward_freeze_receipt(
    rows: Sequence[Mapping[str, Any]],
    *,
    freeze_ts_ms: int,
    parameter_frozen: bool = True,
    timestamp_field: str = "signal_ts_ms",
) -> dict[str, Any]:
    """Reject any forward observation that precedes the immutable freeze."""
    if isinstance(freeze_ts_ms, bool) or not isinstance(freeze_ts_ms, int) or freeze_ts_ms < 0:
        return _base("UNMEASURABLE", reason="invalid_freeze")
    if parameter_frozen is not True:
        return _base("REJECTED", reason="parameters_not_frozen")
    invalid = []
    for row in rows or ():
        if not isinstance(row, Mapping) or not isinstance(row.get(timestamp_field), int) or isinstance(row.get(timestamp_field), bool):
            return _base("UNMEASURABLE", reason="invalid_forward_row")
        if row[timestamp_field] < freeze_ts_ms:
            invalid.append(row.get(timestamp_field))
    return _base(
        "PROVEN" if not invalid and rows else ("MORE_DATA" if not rows else "REJECTED"),
        verdict="FORWARD_AFTER_FREEZE" if not invalid and rows else "FORWARD_BEFORE_FREEZE",
        freeze_ts_ms=freeze_ts_ms,
        rows=len(rows or ()),
        invalid_timestamps=invalid,
    )


def oos_retuning_revocation_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Revoke OOS evidence that was reused for tuning or held-out retuning."""
    if not rows:
        return _base("MORE_DATA", reason="empty_oos")
    violations = [
        str(row.get("episode_id") or index)
        for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("used_for_tuning") is True
        or row.get("retuned_on_heldout") is True
    ]
    return _base(
        "PROVEN" if not violations else "REJECTED",
        verdict="OOS_REVOKED_IF_RETUNED" if not violations else "OOS_RETUNING_DETECTED",
        rows=len(rows),
        violations=violations,
    )


def paper_lane_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require explicit PAPER labels for shadow, replay and forward evidence."""
    allowed = {"shadow", "replay", "forward_paper"}
    if not rows:
        return _base("MORE_DATA", reason="empty_lane")
    invalid = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or row.get("lane") not in allowed or row.get("paper_read_only") is not True or row.get("real_execution") is not False:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="PAPER_LANES_EXPLICIT" if not invalid else "NON_PAPER_LANE",
        rows=len(rows),
        invalid_rows=invalid,
    )


def forward_coverage_receipt(
    rows: Sequence[Mapping[str, Any]],
    *,
    window_start_ms: int,
    window_end_ms: int,
    start_field: str = "start_ts_ms",
    end_field: str = "end_ts_ms",
) -> dict[str, Any]:
    """Measure observed forward duration and report gaps without imputing them."""
    if isinstance(window_start_ms, bool) or isinstance(window_end_ms, bool) or not isinstance(window_start_ms, int) or not isinstance(window_end_ms, int) or window_end_ms <= window_start_ms:
        return _base("UNMEASURABLE", reason="invalid_forward_window")
    intervals: list[tuple[int, int]] = []
    for row in rows or ():
        if not isinstance(row, Mapping):
            return _base("UNMEASURABLE", reason="invalid_coverage_row")
        start, end = row.get(start_field), row.get(end_field)
        if isinstance(start, bool) or isinstance(end, bool) or not isinstance(start, int) or not isinstance(end, int) or end <= start:
            return _base("UNMEASURABLE", reason="invalid_interval")
        intervals.append((start, end))
    if not intervals:
        return _base("MORE_DATA", reason="empty_forward_coverage")
    intervals.sort()
    cursor = window_start_ms
    gaps: list[tuple[int, int]] = []
    covered = 0
    for start, end in intervals:
        if end <= window_start_ms or start >= window_end_ms:
            continue
        clipped_start, clipped_end = max(start, window_start_ms), min(end, window_end_ms)
        if clipped_start > cursor:
            gaps.append((cursor, clipped_start))
        if clipped_end > cursor:
            covered += clipped_end - max(cursor, clipped_start)
            cursor = max(cursor, clipped_end)
    if cursor < window_end_ms:
        gaps.append((cursor, window_end_ms))
    duration = window_end_ms - window_start_ms
    return _base(
        "PROVEN",
        verdict="FORWARD_COVERAGE_MEASURED",
        window_duration_ms=duration,
        covered_duration_ms=max(0, covered),
        coverage_ratio=covered / duration,
        gaps=gaps,
    )


def observed_liquidation_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require observed book marks for liquidation valuation; missing marks fail closed."""
    if not rows:
        return _base("MORE_DATA", reason="empty_liquidation_sample")
    invalid = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            invalid.append(index)
            continue
        try:
            price = float(row.get("observed_liquidation_price"))
            quantity = float(row.get("quantity"))
        except (TypeError, ValueError):
            invalid.append(index)
            continue
        if not math.isfinite(price) or not math.isfinite(quantity) or price <= 0 or quantity <= 0 or row.get("book_observed") is not True:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="OBSERVED_BOOK_LIQUIDATION" if not invalid else "LIQUIDATION_MARK_MISSING",
        rows=len(rows),
        invalid_rows=invalid,
    )


def dataset_cutoff_receipt(
    rows: Sequence[Mapping[str, Any]],
    *,
    oos_start_ms: int,
    manifest_hash: str,
    timestamp_field: str = "source_ts_ms",
) -> dict[str, Any]:
    """Bind every source row to a manifest and require it to respect OOS cutoff."""
    if not isinstance(oos_start_ms, int) or isinstance(oos_start_ms, bool) or oos_start_ms <= 0 or not isinstance(manifest_hash, str) or len(manifest_hash) != 64:
        return _base("UNMEASURABLE", reason="invalid_cutoff_manifest")
    violations = []
    for index, row in enumerate(rows or ()):
        if not isinstance(row, Mapping) or row.get("manifest_hash") != manifest_hash or not isinstance(row.get(timestamp_field), int) or isinstance(row.get(timestamp_field), bool):
            violations.append(index)
            continue
        if row[timestamp_field] >= oos_start_ms:
            violations.append(index)
    return _base(
        "PROVEN" if rows and not violations else ("MORE_DATA" if not rows else "REJECTED"),
        verdict="DATASET_CUTOFF_ALIGNED" if rows and not violations else "DATASET_CUTOFF_VIOLATION",
        rows=len(rows or ()),
        oos_start_ms=oos_start_ms,
        manifest_hash=manifest_hash,
        violations=violations,
    )


def extreme_trade_robustness_receipt(
    rows: Sequence[Mapping[str, Any]],
    *,
    value_field: str = "net_pnl_bps",
    top_n: int = 1,
) -> dict[str, Any]:
    """Recompute a diagnostic aggregate with the largest positive trades removed."""
    if not isinstance(top_n, int) or isinstance(top_n, bool) or top_n < 1:
        return _base("UNMEASURABLE", reason="invalid_top_n")
    try:
        values = [float(row.get(value_field)) for row in rows or () if isinstance(row, Mapping)]
    except (TypeError, ValueError):
        return _base("UNMEASURABLE", reason="invalid_trade_value")
    if len(values) <= top_n or not all(math.isfinite(value) for value in values):
        return _base("MORE_DATA", reason="insufficient_finite_trades")
    ordered = sorted(values, reverse=True)
    retained = ordered[top_n:]
    return _base(
        "PROVEN",
        verdict="EXTREME_TRADE_SENSITIVITY_MEASURED",
        total_trades=len(values),
        removed_top_n=top_n,
        full_mean=sum(values) / len(values),
        trimmed_mean=sum(retained) / len(retained),
    )


def same_cost_champion_challenger_receipt(
    champion: Mapping[str, Any],
    challenger: Mapping[str, Any],
    *,
    cost_fields: Sequence[str] = ("fees_bps", "spread_bps", "slippage_bps", "latency_bps", "funding_bps"),
) -> dict[str, Any]:
    """Compare two candidates only when their explicit cost model is identical."""
    if not isinstance(champion, Mapping) or not isinstance(challenger, Mapping) or not cost_fields:
        return _base("UNMEASURABLE", reason="invalid_candidate_or_cost_contract")
    missing = [field for field in cost_fields if field not in champion or field not in challenger]
    if missing:
        return _base("UNMEASURABLE", reason="missing_cost_fields", missing_cost_fields=missing)
    equal = all(champion[field] == challenger[field] for field in cost_fields)
    return _base(
        "PROVEN" if equal else "REJECTED",
        verdict="SAME_COST_MODEL" if equal else "COST_MODEL_MISMATCH",
        cost_fields=list(cost_fields),
        cost_model_equal=equal,
    )


def technical_economic_separation_receipt(
    technical: Mapping[str, Any],
    economic: Mapping[str, Any],
) -> dict[str, Any]:
    """Keep technical correctness separate from economic certification."""
    if not isinstance(technical, Mapping) or not isinstance(economic, Mapping):
        return _base("UNMEASURABLE", reason="invalid_receipt")
    technical_ok = technical.get("status") in {"PROVEN", "PASS", "COMPLETED"}
    economic_ok = economic.get("status") in {"PROVEN", "COMPLETED"}
    return _base(
        "PROVEN" if technical_ok and economic_ok else "UNMEASURABLE",
        verdict="SEPARATE_CERTIFICATION_LANES" if technical_ok and economic_ok else "INCOMPLETE_LANE",
        technical_status=technical.get("status"),
        economic_status=economic.get("status"),
        technical_does_not_promote_economic=True,
    )


def champion_drift_receipt(
    baseline_values: Sequence[float],
    observed_values: Sequence[float],
    *,
    degradation_threshold: float = 0.0,
) -> dict[str, Any]:
    """Detect observed champion drift and degrade the research status."""
    if not baseline_values or not observed_values or degradation_threshold < 0:
        return _base("MORE_DATA", reason="insufficient_drift_observations")
    try:
        baseline = [float(value) for value in baseline_values]
        observed = [float(value) for value in observed_values]
    except (TypeError, ValueError):
        return _base("UNMEASURABLE", reason="invalid_drift_values")
    if not all(math.isfinite(value) for value in baseline + observed):
        return _base("UNMEASURABLE", reason="non_finite_drift_values")
    baseline_mean = sum(baseline) / len(baseline)
    observed_mean = sum(observed) / len(observed)
    drop = baseline_mean - observed_mean
    return _base(
        "PROVEN",
        verdict="DEGRADED" if drop > degradation_threshold else "STABLE",
        baseline_mean=baseline_mean,
        observed_mean=observed_mean,
        degradation=drop,
        degradation_threshold=degradation_threshold,
    )


def measured_improvement_freeze_receipt(
    *,
    before_hash: str,
    after_hash: str,
    measured: bool,
    rewritten_after_freeze: bool = False,
) -> dict[str, Any]:
    """Freeze a measured improvement and reject post-freeze rewrites."""
    valid = all(isinstance(value, str) and len(value) == 64 for value in (before_hash, after_hash))
    if not valid:
        return _base("UNMEASURABLE", reason="invalid_snapshot_hash")
    if rewritten_after_freeze:
        return _base("REJECTED", reason="post_freeze_rewrite")
    return _base(
        "PROVEN" if measured is True else "MORE_DATA",
        verdict="MEASURED_IMPROVEMENT_FROZEN" if measured is True else "IMPROVEMENT_NOT_MEASURED",
        before_hash=before_hash,
        after_hash=after_hash,
        measured=measured,
    )


def absolute_gain_receipt(
    champion: Mapping[str, Any],
    challenger: Mapping[str, Any],
    *,
    absolute_field: str = "net_pnl_usd",
    sample_field: str = "sample_count",
) -> dict[str, Any]:
    """Require an absolute, costed comparison instead of a relative-only gain."""
    try:
        champion_value = float(champion[absolute_field])
        challenger_value = float(challenger[absolute_field])
        champion_sample = int(champion[sample_field])
        challenger_sample = int(challenger[sample_field])
    except (KeyError, TypeError, ValueError):
        return _base("UNMEASURABLE", reason="absolute_comparison_missing")
    if not all(math.isfinite(value) for value in (champion_value, challenger_value)) or min(champion_sample, challenger_sample) <= 0:
        return _base("UNMEASURABLE", reason="absolute_comparison_invalid")
    return _base(
        "PROVEN",
        verdict="ABSOLUTE_GAIN_COMPARABLE",
        champion_absolute=champion_value,
        challenger_absolute=challenger_value,
        absolute_gain=challenger_value - champion_value,
        same_sample_scale=champion_sample == challenger_sample,
    )


def incumbent_preservation_receipt(incumbent: Mapping[str, Any], challenger: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the incumbent when a challenger fails or is negative."""
    if not isinstance(incumbent, Mapping) or not isinstance(challenger, Mapping):
        return _base("UNMEASURABLE", reason="invalid_candidates")
    challenger_status = str(challenger.get("status") or "").upper()
    incumbent_status = str(incumbent.get("status") or "").upper()
    preserve = challenger_status in {"REJECTED", "NEGATIVE", "FAILED", "MORE_DATA", "UNMEASURABLE"} and incumbent_status not in {"REJECTED", "FAILED"}
    return _base(
        "PROVEN" if preserve else "REJECTED",
        verdict="INCUMBENT_PRESERVED" if preserve else "INCUMBENT_REPLACEMENT_NOT_SAFE",
        incumbent_status=incumbent_status,
        challenger_status=challenger_status,
    )


def semantic_discovery_attempt_registry_receipt(attempts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Count every semantic-discovery attempt, including failed ones."""
    if not attempts:
        return _base("MORE_DATA", reason="empty_attempt_registry")
    ids: set[str] = set()
    invalid = []
    for index, row in enumerate(attempts):
        attempt_id = str(row.get("attempt_id") or "") if isinstance(row, Mapping) else ""
        if not attempt_id or attempt_id in ids:
            invalid.append(index)
        ids.add(attempt_id)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="ALL_DISCOVERY_ATTEMPTS_COUNTED" if not invalid else "DUPLICATE_ATTEMPT_ID",
        n_attempts_total=len(attempts),
        n_attempts_unique=len(ids - {""}),
        invalid_rows=invalid,
    )


def falsified_hypothesis_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Persist falsified hypotheses with their evidence reference."""
    if not rows:
        return _base("MORE_DATA", reason="empty_hypothesis_memory")
    invalid = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not str(row.get("hypothesis_id") or "").strip() or row.get("status") != "FALSIFIED" or not str(row.get("evidence_ref") or "").strip():
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="FALSIFIED_HYPOTHESES_RECORDED" if not invalid else "FALSIFICATION_MEMORY_INCOMPLETE",
        rows=len(rows), invalid_rows=invalid,
    )


def headroom_stagnation_pivot_receipt(values: Sequence[float], *, window: int = 3, epsilon: float = 0.0) -> dict[str, Any]:
    """Trigger a pivot when recent executable headroom has stopped improving."""
    if isinstance(window, bool) or not isinstance(window, int) or window < 2 or epsilon < 0:
        return _base("UNMEASURABLE", reason="invalid_stagnation_window")
    try:
        headroom = [float(value) for value in values]
    except (TypeError, ValueError):
        return _base("UNMEASURABLE", reason="invalid_headroom_values")
    if len(headroom) < window or not all(math.isfinite(value) for value in headroom):
        return _base("MORE_DATA", reason="insufficient_headroom_history")
    recent = headroom[-window:]
    stagnant = max(recent) - min(recent) <= epsilon
    return _base(
        "PROVEN",
        verdict="PIVOT" if stagnant else "CONTINUE",
        recent_headroom=recent,
        stagnant=stagnant,
        epsilon=epsilon,
    )


def information_gain_priority_receipt(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Order experiments by declared information gain without inventing scores."""
    if not candidates:
        return _base("MORE_DATA", reason="empty_experiment_queue")
    parsed = []
    for index, row in enumerate(candidates):
        if not isinstance(row, Mapping) or not str(row.get("candidate_id") or "").strip():
            return _base("UNMEASURABLE", reason=f"invalid_candidate:{index}")
        try:
            gain = float(row.get("information_gain"))
        except (TypeError, ValueError):
            return _base("UNMEASURABLE", reason=f"missing_information_gain:{index}")
        if not math.isfinite(gain):
            return _base("UNMEASURABLE", reason=f"non_finite_information_gain:{index}")
        parsed.append((str(row["candidate_id"]), gain, index))
    ordered = sorted(parsed, key=lambda item: (-item[1], item[2]))
    return _base(
        "PROVEN",
        verdict="INFORMATION_GAIN_PRIORITY",
        ordered_candidates=[candidate_id for candidate_id, _, _ in ordered],
        information_gain={candidate_id: gain for candidate_id, gain, _ in ordered},
    )


def hypothesis_state_receipt(states: Sequence[str]) -> dict[str, Any]:
    """Require distinct hypothesis, frozen and champion states."""
    normalized = {str(state).strip().upper() for state in states or ()}
    required = {"HYPOTHESIS", "FROZEN", "CHAMPION"}
    return _base(
        "PROVEN" if required.issubset(normalized) else "UNMEASURABLE",
        verdict="DISTINCT_RESEARCH_STATES" if required.issubset(normalized) else "STATE_COLLISION_OR_MISSING",
        states=sorted(normalized),
        required_states=sorted(required),
    )


def atomic_freeze_append_receipt(
    *,
    pre_hash: str,
    post_hash: str,
    append_status: str,
    recovered_after_crash: bool,
) -> dict[str, Any]:
    """Validate crash-safe economic-freeze append acknowledgement."""
    valid_hashes = all(isinstance(value, str) and len(value) == 64 for value in (pre_hash, post_hash))
    if not valid_hashes:
        return _base("UNMEASURABLE", reason="invalid_append_hash")
    if append_status not in {"COMMITTED", "RECOVERED"}:
        return _base("REJECTED", reason="append_not_committed")
    return _base(
        "PROVEN" if recovered_after_crash is True else "MORE_DATA",
        verdict="ATOMIC_FREEZE_APPEND_RECOVERED" if recovered_after_crash else "CRASH_RECOVERY_NOT_OBSERVED",
        pre_hash=pre_hash,
        post_hash=post_hash,
        append_status=append_status,
        recovered_after_crash=recovered_after_crash,
    )


__all__ = [
    "independent_episode_receipt", "forward_freeze_receipt", "oos_retuning_revocation_receipt",
    "paper_lane_receipt", "forward_coverage_receipt", "observed_liquidation_receipt",
    "dataset_cutoff_receipt", "extreme_trade_robustness_receipt",
    "same_cost_champion_challenger_receipt", "technical_economic_separation_receipt",
    "champion_drift_receipt", "measured_improvement_freeze_receipt", "absolute_gain_receipt",
    "incumbent_preservation_receipt", "semantic_discovery_attempt_registry_receipt",
    "falsified_hypothesis_receipt", "headroom_stagnation_pivot_receipt",
    "information_gain_priority_receipt", "hypothesis_state_receipt", "atomic_freeze_append_receipt",
]
