"""Fail-closed controls for Copy-Vault launch, cost and observability contracts.

The functions in this module are deliberately small evidence gates.  They only
consume observations already supplied by a caller; they do not collect data,
launch a process, infer a value, or grant execution authority.  Missing or
incoherent observations remain explicit ``MORE_DATA``/``UNMEASURABLE`` or
``REJECTED`` outcomes.
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


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def net_threshold_vs_daily_target_receipt(
    net_threshold_usd: Any, *, daily_target_usd: Any = 5.0
) -> dict[str, Any]:
    """Keep a local acceptance threshold distinct from the absolute daily target."""
    threshold, target = _number(net_threshold_usd), _number(daily_target_usd)
    if threshold is None or target is None or threshold <= 0 or target <= 0:
        return _base("UNMEASURABLE", reason="invalid_threshold_or_target")
    return _base(
        "PROVEN",
        verdict="NET_THRESHOLD_DISTINCT_FROM_ABSOLUTE_TARGET",
        net_threshold_usd=threshold,
        absolute_daily_target_usd=target,
        threshold_is_target_equal=threshold == target,
    )


def position_vs_global_budget_receipt(
    rows: Sequence[Mapping[str, Any]],
    *,
    position_budget_usd: Any,
    global_budget_usd: Any,
) -> dict[str, Any]:
    """Validate per-position caps separately from the aggregate paper budget."""
    position_cap, global_cap = _number(position_budget_usd), _number(global_budget_usd)
    if position_cap is None or global_cap is None or position_cap <= 0 or global_cap <= 0:
        return _base("UNMEASURABLE", reason="invalid_budget")
    if not rows:
        return _base("MORE_DATA", reason="empty_position_budget_sample")
    allocations: list[float] = []
    for row in rows:
        value = _number(row.get("allocation_usd")) if isinstance(row, Mapping) else None
        if value is None or value < 0:
            return _base("UNMEASURABLE", reason="invalid_position_allocation")
        allocations.append(value)
    violations = [i for i, value in enumerate(allocations) if value > position_cap]
    total = sum(allocations)
    if total > global_cap:
        violations.append("global_budget")
    return _base(
        "PROVEN" if not violations else "REJECTED",
        verdict="POSITION_AND_GLOBAL_BUDGETS_DISTINCT" if not violations else "BUDGET_VIOLATION",
        position_budget_usd=position_cap,
        global_budget_usd=global_cap,
        total_allocated_usd=total,
        allocation_count=len(allocations),
        violations=violations,
    )


def maker_l2_execution_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require maker claims to reference an observed aggregated L2 boundary."""
    if not rows:
        return _base("MORE_DATA", reason="empty_maker_l2_sample")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            invalid.append(index)
            continue
        if row.get("execution_style") != "maker" or row.get("l2_aggregated") is not True:
            invalid.append(index)
            continue
        if not str(row.get("native_event_id") or "").strip() or _number(row.get("observed_at_ms")) is None:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="MAKER_ON_OBSERVED_AGGREGATED_L2" if not invalid else "MAKER_L2_OBSERVATION_MISSING",
        rows=len(rows),
        invalid_rows=invalid,
    )


def runtime_fee_schedule_receipt(
    schedule: Mapping[str, Any], *, required_styles: Sequence[str] = ("maker", "taker")
) -> dict[str, Any]:
    """Require explicit, effective runtime fee tiers instead of defaults."""
    if not isinstance(schedule, Mapping) or not required_styles:
        return _base("UNMEASURABLE", reason="invalid_fee_schedule")
    missing = [style for style in required_styles if style not in schedule]
    if missing:
        return _base("UNMEASURABLE", reason="missing_fee_styles", missing_styles=missing)
    invalid: list[str] = []
    for style in required_styles:
        tier = schedule.get(style)
        if not isinstance(tier, Mapping) or not str(tier.get("schedule_id") or "").strip():
            invalid.append(style)
            continue
        if _number(tier.get("fee_bps")) is None or _number(tier.get("effective_from_ms")) is None:
            invalid.append(style)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="EXPLICIT_RUNTIME_FEE_SCHEDULE" if not invalid else "INVALID_RUNTIME_FEE_SCHEDULE",
        styles=list(required_styles),
        invalid_styles=invalid,
    )


def age_adjusted_cost_receipt(
    rows: Sequence[Mapping[str, Any]], *, max_age_ms: int = 90_000
) -> dict[str, Any]:
    """Accept spread/slippage observations only while their age is bounded."""
    if not rows or _positive_int(max_age_ms) is None:
        return _base("MORE_DATA" if not rows else "UNMEASURABLE", reason="empty_or_invalid_age_window")
    stale: list[int] = []
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            invalid.append(index)
            continue
        signal, observed = _number(row.get("signal_ts_ms")), _number(row.get("observed_ts_ms"))
        cost = _number(row.get("cost_bps"))
        if signal is None or observed is None or cost is None or observed < signal or cost < 0:
            invalid.append(index)
            continue
        if observed - signal > max_age_ms:
            stale.append(index)
    status = "PROVEN" if not stale and not invalid else "UNMEASURABLE"
    return _base(
        status,
        verdict="AGE_BOUNDED_COST" if status == "PROVEN" else "STALE_OR_INVALID_COST",
        rows=len(rows),
        max_age_ms=max_age_ms,
        stale_rows=stale,
        invalid_rows=invalid,
    )


def stop_trailing_hypothesis_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep stop/trailing behavior as explicitly evidenced hypotheses."""
    allowed = {"stop", "trailing"}
    if not rows:
        return _base("MORE_DATA", reason="empty_stop_trailing_hypotheses")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or row.get("hypothesis_type") not in allowed:
            invalid.append(index)
            continue
        if not str(row.get("hypothesis_id") or "").strip() or not str(row.get("evidence_ref") or "").strip():
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="STOP_TRAILING_HYPOTHESES_REVALIDATED" if not invalid else "HYPOTHESIS_EVIDENCE_MISSING",
        rows=len(rows),
        invalid_rows=invalid,
    )


def fee_model_reset_receipt(
    before: Mapping[str, Any], after: Mapping[str, Any], *, reset_event_id: str
) -> dict[str, Any]:
    """Require a reset to preserve the complete fee model, not just a label."""
    if not isinstance(before, Mapping) or not isinstance(after, Mapping) or not str(reset_event_id).strip():
        return _base("UNMEASURABLE", reason="invalid_reset_contract")
    required = {"fee_bps", "maker_rebate_bps", "spread_bps", "slippage_bps"}
    missing = sorted((required - set(before)) | (required - set(after)))
    if missing:
        return _base("UNMEASURABLE", reason="fee_model_fields_missing", missing_fields=missing)
    equal = all(before[field] == after[field] for field in required)
    return _base(
        "PROVEN" if equal else "REJECTED",
        verdict="FEE_MODEL_PRESERVED_ON_RESET" if equal else "FEE_MODEL_CHANGED_ON_RESET",
        reset_event_id=reset_event_id,
        model_fields=sorted(required),
    )


def no_trade_value_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Audit NO_TRADE value per configuration without treating no observations as zero value."""
    if not rows:
        return _base("MORE_DATA", reason="empty_no_trade_configurations")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        sample_count = row.get("sample_count") if isinstance(row, Mapping) else None
        value = _number(row.get("no_trade_value_bps")) if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or not str(row.get("config_id") or "").strip() or _positive_int(sample_count) is None or value is None:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="NO_TRADE_VALUE_BY_CONFIGURATION" if not invalid else "NO_TRADE_VALUE_MISSING",
        configurations=len(rows),
        invalid_rows=invalid,
    )


def boot_phase_timing_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require complete, monotonic timing boundaries for every boot phase."""
    if not rows:
        return _base("MORE_DATA", reason="empty_boot_phases")
    invalid: list[int] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            invalid.append(index)
            continue
        phase = str(row.get("phase") or "").strip()
        start, end = _number(row.get("start_ts_ms")), _number(row.get("end_ts_ms"))
        if not phase or phase in seen or start is None or end is None or end < start:
            invalid.append(index)
        seen.add(phase)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="BOOT_PHASES_TIMED" if not invalid else "BOOT_PHASE_TIMING_INVALID",
        phase_count=len(rows),
        invalid_rows=invalid,
    )


def warmup_redundancy_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reject a boot plan that still contains a redundant market warmup."""
    if not rows:
        return _base("MORE_DATA", reason="empty_warmup_plan")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("step_id") or "").strip()
        or row.get("redundant_market_warmup") is True
    ]
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="REDUNDANT_MARKET_WARMUP_REMOVED" if not invalid else "REDUNDANT_MARKET_WARMUP_PRESENT",
        steps=len(rows),
        invalid_rows=invalid,
    )


def collector_cost_cap_receipt(
    rows: Sequence[Mapping[str, Any]], *, max_cost_usd: Any
) -> dict[str, Any]:
    """Bound duplicated BBO collector cost using observed per-cycle cost."""
    cap = _number(max_cost_usd)
    if cap is None or cap < 0:
        return _base("UNMEASURABLE", reason="invalid_collector_cost_cap")
    if not rows:
        return _base("MORE_DATA", reason="empty_collector_cost_sample")
    invalid = []
    for index, row in enumerate(rows):
        cost = _number(row.get("cost_usd")) if isinstance(row, Mapping) else None
        if not isinstance(row, Mapping) or not str(row.get("collector_id") or "").strip() or cost is None or cost < 0 or cost > cap:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="BBO_COLLECTOR_COST_CAPPED" if not invalid else "BBO_COLLECTOR_COST_OVER_CAP",
        max_cost_usd=cap,
        invalid_rows=invalid,
    )


def userfills_quota_receipt(
    streams: Sequence[Mapping[str, Any]], *, max_concurrent: int = 2
) -> dict[str, Any]:
    """Enforce an explicit upper bound on simultaneous userFills streams."""
    if not streams:
        return _base("MORE_DATA", reason="empty_userfills_streams")
    if _positive_int(max_concurrent) is None:
        return _base("UNMEASURABLE", reason="invalid_stream_quota")
    invalid = [
        index for index, stream in enumerate(streams)
        if not isinstance(stream, Mapping) or not str(stream.get("stream_id") or "").strip() or stream.get("enabled") is not True
    ]
    active = sum(1 for stream in streams if isinstance(stream, Mapping) and stream.get("enabled") is True)
    if active > max_concurrent:
        invalid.append("quota")
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="USERFILLS_QUOTA_RESPECTED" if not invalid else "USERFILLS_QUOTA_EXCEEDED",
        active_streams=active,
        max_concurrent=max_concurrent,
        invalid_rows=invalid,
    )


def cpu_budget_receipt(
    samples: Sequence[Mapping[str, Any]], *, max_cpu_percent: Any
) -> dict[str, Any]:
    """Check CPU observations while an optional Salad process is active."""
    cap = _number(max_cpu_percent)
    if cap is None or cap < 0 or cap > 100:
        return _base("UNMEASURABLE", reason="invalid_cpu_budget")
    if not samples:
        return _base("MORE_DATA", reason="empty_cpu_sample")
    invalid = []
    for index, sample in enumerate(samples):
        cpu = _number(sample.get("cpu_percent")) if isinstance(sample, Mapping) else None
        if not isinstance(sample, Mapping) or sample.get("salad_active") is not True or cpu is None or cpu < 0 or cpu > 100 or cpu > cap:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="CPU_BUDGET_WITH_SALAD_RESPECTED" if not invalid else "CPU_BUDGET_EXCEEDED",
        max_cpu_percent=cap,
        invalid_rows=invalid,
    )


def poller_latency_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Calibrate a poller cadence from observed latency without imputing latency."""
    if not rows:
        return _base("MORE_DATA", reason="empty_poller_latency_sample")
    latencies: list[float] = []
    invalid: list[int] = []
    for index, row in enumerate(rows):
        latency = _number(row.get("latency_ms")) if isinstance(row, Mapping) else None
        if latency is None or latency < 0:
            invalid.append(index)
        else:
            latencies.append(latency)
    if invalid or not latencies:
        return _base("UNMEASURABLE", reason="invalid_poller_latency", invalid_rows=invalid)
    return _base(
        "PROVEN",
        verdict="POLLER_CADENCE_CALIBRATED_FROM_OBSERVATIONS",
        observations=len(latencies),
        max_latency_ms=max(latencies),
        recommended_cadence_ms=max(1, math.ceil(max(latencies) * 1.25)),
    )


def decision_horizon_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Refuse a strategy whose observed p99 decision time exceeds its horizon."""
    if not rows:
        return _base("MORE_DATA", reason="empty_decision_horizon_sample")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        p99 = _number(row.get("p99_decision_ms")) if isinstance(row, Mapping) else None
        horizon = _number(row.get("horizon_ms")) if isinstance(row, Mapping) else None
        if p99 is None or horizon is None or p99 < 0 or horizon <= 0 or p99 > horizon:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="DECISION_P99_WITHIN_HORIZON" if not invalid else "DECISION_P99_EXCEEDS_HORIZON",
        invalid_rows=invalid,
    )


def warmup_overhead_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Measure synchronous warmup overhead against an observed batched path."""
    if not rows:
        return _base("MORE_DATA", reason="empty_warmup_overhead_sample")
    invalid: list[int] = []
    reductions: list[float] = []
    for index, row in enumerate(rows):
        sync_ms = _number(row.get("sync_cli_ms")) if isinstance(row, Mapping) else None
        batched_ms = _number(row.get("batched_cli_ms")) if isinstance(row, Mapping) else None
        if sync_ms is None or batched_ms is None or sync_ms < 0 or batched_ms < 0 or batched_ms > sync_ms:
            invalid.append(index)
        else:
            reductions.append(sync_ms - batched_ms)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="WARMUP_OVERHEAD_REDUCED" if not invalid else "WARMUP_OVERHEAD_NOT_REDUCED",
        measured_rows=len(rows),
        total_reduction_ms=sum(reductions),
        invalid_rows=invalid,
    )


def core_wallet_scan_receipt(
    plans: Sequence[Mapping[str, Any]], *, core_wallet_limit: int = 100
) -> dict[str, Any]:
    """Require a bounded CORE boot plan instead of a full wallet scan."""
    if not plans:
        return _base("MORE_DATA", reason="empty_core_scan_plan")
    if _positive_int(core_wallet_limit) is None:
        return _base("UNMEASURABLE", reason="invalid_core_wallet_limit")
    invalid = []
    for index, plan in enumerate(plans):
        count = plan.get("wallet_count") if isinstance(plan, Mapping) else None
        if not isinstance(plan, Mapping) or plan.get("profile") != "core" or _positive_int(count) is None or count > core_wallet_limit or plan.get("full_scan") is True:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="CORE_WALLET_SCAN_BOUNDED" if not invalid else "CORE_WALLET_SCAN_UNBOUNDED",
        core_wallet_limit=core_wallet_limit,
        invalid_rows=invalid,
    )


def io_pressure_receipt(
    samples: Sequence[Mapping[str, Any]], *, max_queue_depth: Any = 1000
) -> dict[str, Any]:
    """Measure recorder/UI IO pressure from observed counters and queue depth."""
    cap = _number(max_queue_depth)
    if cap is None or cap < 0:
        return _base("UNMEASURABLE", reason="invalid_io_queue_cap")
    if not samples:
        return _base("MORE_DATA", reason="empty_io_pressure_sample")
    invalid: list[int] = []
    for index, sample in enumerate(samples):
        if not isinstance(sample, Mapping):
            invalid.append(index)
            continue
        recorder = _number(sample.get("recorder_iops"))
        ui = _number(sample.get("ui_iops"))
        queue = _number(sample.get("queue_depth"))
        if recorder is None or ui is None or queue is None or recorder < 0 or ui < 0 or queue < 0 or queue > cap:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="RECORDER_UI_IO_PRESSURE_MEASURED" if not invalid else "RECORDER_UI_IO_PRESSURE_OVER_CAP",
        max_queue_depth=cap,
        invalid_rows=invalid,
    )


def liveness_readiness_receipt(
    liveness: Mapping[str, Any], readiness: Mapping[str, Any]
) -> dict[str, Any]:
    """Keep liveness and readiness distinct and prevent readiness without liveness."""
    if not isinstance(liveness, Mapping) or not isinstance(readiness, Mapping):
        return _base("UNMEASURABLE", reason="invalid_health_payload")
    live = liveness.get("live")
    ready = readiness.get("ready")
    if not isinstance(live, bool) or not isinstance(ready, bool):
        return _base("UNMEASURABLE", reason="health_state_missing")
    coherent = not ready or live
    return _base(
        "PROVEN" if coherent else "REJECTED",
        verdict="LIVENESS_READINESS_SEPARATED" if coherent else "READINESS_WITHOUT_LIVENESS",
        liveness=live,
        readiness=ready,
    )


def source_module_status_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require explicit per-source/module states instead of one global green flag."""
    allowed = {"ACTIVE", "DEGRADED", "DOWN", "UNKNOWN"}
    if not rows:
        return _base("MORE_DATA", reason="empty_source_module_status")
    invalid: list[int] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not str(row.get("source") or "").strip() or not str(row.get("module") or "").strip() or row.get("status") not in allowed:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="SOURCE_MODULE_STATUS_EXPLICIT" if not invalid else "SOURCE_MODULE_STATUS_MISSING",
        rows=len(rows),
        invalid_rows=invalid,
    )


__all__ = [
    "net_threshold_vs_daily_target_receipt",
    "position_vs_global_budget_receipt",
    "maker_l2_execution_receipt",
    "runtime_fee_schedule_receipt",
    "age_adjusted_cost_receipt",
    "stop_trailing_hypothesis_receipt",
    "fee_model_reset_receipt",
    "no_trade_value_receipt",
    "boot_phase_timing_receipt",
    "warmup_redundancy_receipt",
    "collector_cost_cap_receipt",
    "userfills_quota_receipt",
    "cpu_budget_receipt",
    "poller_latency_receipt",
    "decision_horizon_receipt",
    "warmup_overhead_receipt",
    "core_wallet_scan_receipt",
    "io_pressure_receipt",
    "liveness_readiness_receipt",
    "source_module_status_receipt",
]
