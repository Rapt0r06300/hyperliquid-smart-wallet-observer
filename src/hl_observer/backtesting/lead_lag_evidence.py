"""Versioned contract shared by offline lead-lag research and the live shadow reader.

The contract is deliberately strict.  A JSON file is not evidence merely because it
contains a positive number: dataset and pipeline identities, observability, costs,
sample size and robustness gates all have to be present and pass.
"""
from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "hypersmart.lead_lag_frozen_evidence.v2"
SUPPORTED_HORIZONS_MS = (50.0, 100.0, 250.0, 500.0, 1000.0)
REQUIRED_CRITERIA = (
    "minimum_sample",
    "observable_horizon",
    "net_positive",
    "period_stability",
    "placebo_beaten",
    "controls_non_winning",
    "costs_executable",
    "bootstrap_positive",
    "pbo_acceptable",
    "dsr_acceptable",
    "latency_budget_passed",
)


class FrozenLeadLagEvidenceError(ValueError):
    """Raised when an artefact cannot authorize a shadow/runtime signal."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = str(code)
        self.detail = str(detail)
        super().__init__(f"{self.code}: {self.detail}" if self.detail else self.code)


def _finite_number(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise FrozenLeadLagEvidenceError("NON_NUMERIC_VALUE", repr(value)) from exc
    if not math.isfinite(number):
        raise FrozenLeadLagEvidenceError("NON_FINITE_VALUE", repr(value))
    return number


def _sha256_identity(value: Any, field: str) -> str:
    identity = str(value or "")
    if not identity.startswith("sha256:") or len(identity) != 71:
        raise FrozenLeadLagEvidenceError("INVALID_HASH", field)
    try:
        int(identity[7:], 16)
    except ValueError as exc:
        raise FrozenLeadLagEvidenceError("INVALID_HASH", field) from exc
    return identity


def estimate_alpha_half_life_ms(edges_by_horizon: Mapping[float, float]) -> float | None:
    """Estimate the first measured 50% edge-decay crossing.

    The function interpolates only between observed horizons.  It deliberately
    refuses to extrapolate when the recorded edge never crosses half of its
    earliest value.
    """

    points = sorted(
        (
            _finite_number(horizon),
            _finite_number(edge),
        )
        for horizon, edge in edges_by_horizon.items()
    )
    if not points or points[0][1] <= 0:
        return None
    half_edge = points[0][1] / 2.0
    previous_horizon, previous_edge = points[0]
    if previous_edge <= half_edge:
        return previous_horizon
    for horizon, edge in points[1:]:
        if edge <= half_edge:
            if edge == previous_edge:
                return horizon
            ratio = (previous_edge - half_edge) / (previous_edge - edge)
            return previous_horizon + ratio * (horizon - previous_horizon)
        previous_horizon, previous_edge = horizon, edge
    return None


def validate_frozen_evidence(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize a promoted lead-lag evidence artefact.

    Rejected or incomplete research artefacts remain useful for audit, but they
    cannot be consumed by the runtime and therefore fail here.
    """

    if str(payload.get("schema_version") or "") != SCHEMA_VERSION:
        raise FrozenLeadLagEvidenceError("UNSUPPORTED_SCHEMA")
    if str(payload.get("strategy") or "") != "lead_lag_shadow":
        raise FrozenLeadLagEvidenceError("WRONG_STRATEGY")
    if str(payload.get("promotion_status") or "") != "PROMOTED":
        raise FrozenLeadLagEvidenceError(
            "EVIDENCE_NOT_PROMOTED", str(payload.get("promotion_status") or "MISSING")
        )

    _sha256_identity(payload.get("dataset_hash"), "dataset_hash")
    _sha256_identity(payload.get("pipeline_hash"), "pipeline_hash")
    if not str(payload.get("freeze_ts") or "") or int(payload.get("freeze_ts_ms") or 0) <= 0:
        raise FrozenLeadLagEvidenceError("INVALID_FREEZE_TIME")

    coins = tuple(sorted({str(coin).upper() for coin in payload.get("coins", ()) if coin}))
    controls = tuple(
        sorted({str(coin).upper() for coin in payload.get("control_coins", ()) if coin})
    )
    if not coins or set(coins) & set(controls):
        raise FrozenLeadLagEvidenceError("INVALID_COIN_SCOPE")

    requested = tuple(_finite_number(item) for item in payload.get("requested_horizons_ms", ()))
    observable = tuple(_finite_number(item) for item in payload.get("observable_horizons_ms", ()))
    supported = set(SUPPORTED_HORIZONS_MS)
    if not requested or any(item not in supported for item in requested):
        raise FrozenLeadLagEvidenceError("UNSUPPORTED_REQUESTED_HORIZON")
    if not observable or any(item not in requested for item in observable):
        raise FrozenLeadLagEvidenceError("UNOBSERVABLE_HORIZON_SCOPE")

    criteria = payload.get("criteria")
    if not isinstance(criteria, Mapping):
        raise FrozenLeadLagEvidenceError("MISSING_CRITERIA")
    failed = [name for name in REQUIRED_CRITERIA if criteria.get(name) is not True]
    if failed:
        raise FrozenLeadLagEvidenceError("FAILED_PROMOTION_CRITERIA", ",".join(failed))

    raw_edges = payload.get("edge_net_par_horizon_bps")
    raw_samples = payload.get("sample_n_by_horizon")
    if not isinstance(raw_edges, Mapping) or not isinstance(raw_samples, Mapping):
        raise FrozenLeadLagEvidenceError("MISSING_HORIZON_EVIDENCE")
    min_events = int(payload.get("minimum_events") or 0)
    if min_events <= 0:
        raise FrozenLeadLagEvidenceError("INVALID_MINIMUM_EVENTS")

    edges: dict[float, float] = {}
    samples: dict[float, int] = {}
    for horizon in observable:
        key = str(int(horizon) if horizon.is_integer() else horizon)
        if key not in raw_edges or key not in raw_samples:
            raise FrozenLeadLagEvidenceError("HORIZON_EVIDENCE_MISMATCH", key)
        edge = _finite_number(raw_edges[key])
        sample_n = int(raw_samples[key])
        if edge <= 0 or sample_n < min_events:
            raise FrozenLeadLagEvidenceError("NON_PROMOTABLE_HORIZON", key)
        edges[horizon] = edge
        samples[horizon] = sample_n

    costs = payload.get("costs")
    if not isinstance(costs, Mapping) or costs.get("executable") is not True:
        raise FrozenLeadLagEvidenceError("UNEXECUTABLE_COST_MODEL")
    total_cost_bps = _finite_number(costs.get("round_trip_bps"))
    if total_cost_bps < 0:
        raise FrozenLeadLagEvidenceError("NEGATIVE_COST_MODEL")

    latency_budget = payload.get("latency_budget")
    if not isinstance(latency_budget, Mapping):
        raise FrozenLeadLagEvidenceError("MISSING_LATENCY_BUDGET")
    half_life_ms = _finite_number(latency_budget.get("alpha_half_life_p95_ms"))
    end_to_end_latency_ms = _finite_number(
        latency_budget.get("end_to_end_latency_p95_ms")
    )
    safety_margin_ms = _finite_number(latency_budget.get("safety_margin_ms"))
    if half_life_ms <= 0 or end_to_end_latency_ms < 0 or safety_margin_ms < 0:
        raise FrozenLeadLagEvidenceError("INVALID_LATENCY_BUDGET")
    remaining_budget_ms = half_life_ms - end_to_end_latency_ms - safety_margin_ms
    if remaining_budget_ms <= 0:
        raise FrozenLeadLagEvidenceError("ALPHA_HALF_LIFE_BELOW_RUNTIME_LATENCY")

    frequency = payload.get("frequency")
    if not isinstance(frequency, Mapping):
        raise FrozenLeadLagEvidenceError("MISSING_FREQUENCY")
    events_per_day = frequency.get("events_per_day")
    if events_per_day is not None:
        events_per_day = _finite_number(events_per_day)
        if events_per_day < 0:
            raise FrozenLeadLagEvidenceError("INVALID_FREQUENCY")

    global_trials = payload.get("global_trials")
    if not isinstance(global_trials, Mapping):
        raise FrozenLeadLagEvidenceError("MISSING_GLOBAL_TRIAL_COUNT")
    if int(global_trials.get("count") or 0) < len(requested):
        raise FrozenLeadLagEvidenceError("UNDERCOUNTED_CLOCK_BOUNDARY_TRIALS")

    normalized = dict(payload)
    normalized["coins"] = list(coins)
    normalized["control_coins"] = list(controls)
    normalized["requested_horizons_ms"] = list(requested)
    normalized["observable_horizons_ms"] = list(observable)
    normalized["edge_net_par_horizon_bps"] = edges
    normalized["sample_n_by_horizon"] = samples
    normalized["costs"] = dict(costs)
    normalized["latency_budget"] = {
        **dict(latency_budget),
        "alpha_half_life_p95_ms": half_life_ms,
        "end_to_end_latency_p95_ms": end_to_end_latency_ms,
        "safety_margin_ms": safety_margin_ms,
        "remaining_budget_ms": remaining_budget_ms,
    }
    normalized["frequency"] = {**dict(frequency), "events_per_day": events_per_day}
    return normalized


def load_frozen_evidence(path: str | Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise FrozenLeadLagEvidenceError("CONFIG_NOT_FOUND") from exc
    except (TypeError, ValueError) as exc:
        raise FrozenLeadLagEvidenceError("CONFIG_INVALID_JSON") from exc
    if not isinstance(payload, Mapping):
        raise FrozenLeadLagEvidenceError("CONFIG_NOT_OBJECT")
    return validate_frozen_evidence(payload)


__all__ = [
    "FrozenLeadLagEvidenceError",
    "REQUIRED_CRITERIA",
    "SCHEMA_VERSION",
    "SUPPORTED_HORIZONS_MS",
    "estimate_alpha_half_life_ms",
    "load_frozen_evidence",
    "validate_frozen_evidence",
]
