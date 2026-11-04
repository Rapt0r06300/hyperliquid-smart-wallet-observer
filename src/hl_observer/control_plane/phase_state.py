"""Authoritative Phase State Schema (Version 1) for Alina SmartFlow."""
from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 1
VALID_PHASES = frozenset({"IDLE", "COLLECT", "ANALYZE"})
VALID_ANALYSIS_STAGES = frozenset({"DRAIN", "QUALITY", "REPLAY", "BACKTEST", "OOS", "FORWARD_PAPER", "PNL_PROOF", "SCOREBOARD", "DONE", None})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


def parse_iso_utc(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"Timestamp must be UTC ISO-8601 ending in Z, got: {value}")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo != timezone.utc:
        raise ValueError(f"Timestamp timezone must be UTC, got: {dt.tzinfo}")
    return dt


@dataclass
class AlinaPhaseState:
    schema_version: int = SCHEMA_VERSION
    phase: str = "IDLE"
    epoch: int = 1
    requested_at_utc: str = field(default_factory=_now)
    collection_started_at_utc: str | None = None
    collection_cutoff_at_utc: str | None = None
    source_collection_epoch: int | None = None
    analysis_stage: str | None = None
    requested_by: str = "operator"
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def content_digest(self) -> str:
        return sha256_json(self.to_dict())

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> AlinaPhaseState:
        allowed = set(cls.__dataclass_fields__)
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Unknown phase state fields: {sorted(unknown)}")

        # Check required fields presence in dict if loading from external JSON
        for req in ("schema_version", "phase", "epoch", "requested_at_utc", "requested_by"):
            if req not in raw:
                raise ValueError(f"Missing required phase state field: {req}")

        obj = cls(**dict(raw))
        validate_phase_state(obj)
        return obj


def validate_phase_state(state: AlinaPhaseState) -> None:
    if state.schema_version != SCHEMA_VERSION:
        raise ValueError(f"Unsupported phase schema version: {state.schema_version}")

    if state.phase not in VALID_PHASES:
        raise ValueError(f"Invalid phase: {state.phase}, must be one of {VALID_PHASES}")

    if not isinstance(state.epoch, int) or isinstance(state.epoch, bool) or state.epoch < 1:
        raise ValueError(f"Epoch must be positive integer, got: {state.epoch}")

    parse_iso_utc(state.requested_at_utc)
    if not isinstance(state.requested_by, str) or not state.requested_by.strip():
        raise ValueError("requested_by must be a non-empty string")
    if state.request_id is not None and (not isinstance(state.request_id, str) or len(state.request_id) != 64 or any(ch not in "0123456789abcdef" for ch in state.request_id)):
        raise ValueError("request_id must be an exact lowercase SHA-256 when present")

    if state.collection_started_at_utc is not None:
        parse_iso_utc(state.collection_started_at_utc)

    if state.collection_cutoff_at_utc is not None:
        parse_iso_utc(state.collection_cutoff_at_utc)

    if state.analysis_stage not in VALID_ANALYSIS_STAGES:
        raise ValueError(f"Invalid analysis_stage: {state.analysis_stage}")

    # Phase-specific invariants
    if state.phase == "COLLECT":
        if state.collection_started_at_utc is None:
            raise ValueError("COLLECT phase requires collection_started_at_utc")
        if state.collection_cutoff_at_utc is not None:
            raise ValueError("COLLECT phase must have null collection_cutoff_at_utc")
        if state.source_collection_epoch is not None:
            raise ValueError("COLLECT phase must have null source_collection_epoch")
        if state.analysis_stage is not None:
            raise ValueError("COLLECT phase must have null analysis_stage")

    elif state.phase == "ANALYZE":
        if (
            state.source_collection_epoch is None
            or isinstance(state.source_collection_epoch, bool)
            or not isinstance(state.source_collection_epoch, int)
            or state.source_collection_epoch < 1
        ):
            raise ValueError("ANALYZE phase requires a valid positive integer source_collection_epoch")
        if state.collection_cutoff_at_utc is None:
            raise ValueError("ANALYZE phase requires collection_cutoff_at_utc")
        if state.analysis_stage is None:
            raise ValueError("ANALYZE phase requires an explicit analysis_stage")

    elif state.phase == "IDLE":
        if any(
            value is not None
            for value in (
                state.collection_started_at_utc,
                state.collection_cutoff_at_utc,
                state.source_collection_epoch,
                state.analysis_stage,
            )
        ):
            raise ValueError("IDLE phase must not retain active collection or analysis fields")

    if state.phase == "ANALYZE":
        started = parse_iso_utc(state.collection_started_at_utc) if state.collection_started_at_utc else None
        cutoff = parse_iso_utc(state.collection_cutoff_at_utc) if state.collection_cutoff_at_utc else None
        if started is None or cutoff is None or cutoff < started:
            raise ValueError("ANALYZE cutoff must be at or after collection start")


def _phase_base(status: str, **values: Any) -> dict[str, Any]:
    """Build a paper/read-only phase evidence receipt.

    These helpers only evaluate supplied evidence.  They never mutate phase state,
    advance an epoch, or convert an incomplete proof into a closure.
    """
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "phase_mutation": False,
        "closure_allowed": False,
        **values,
    }


def _phase_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _phase_finite(value: Any) -> bool:
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _phase_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def phase_state_safety_receipt(state: Any) -> dict[str, Any]:
    """Accept only a complete, valid phase state and remain fail-closed."""
    try:
        candidate = state if isinstance(state, AlinaPhaseState) else AlinaPhaseState.from_dict(state)
        validate_phase_state(candidate)
    except (TypeError, ValueError):
        return _phase_base("REJECTED", verdict="PHASE_STATE_INVALID", fail_closed=True)
    return _phase_base("PROVEN", verdict="PHASE_STATE_VALID", phase=candidate.phase, epoch=candidate.epoch, fail_closed=False)


def walk_forward_to_phase_boundary_receipt(
    walk_forward_result: Any,
    phase_state: Any,
) -> dict[str, Any]:
    """Join walk-forward evidence with an authoritative phase state.

    Both boundaries must be independently valid. This receipt proves only that
    the evidence is admissible for the current phase; it never promotes a
    champion, advances an epoch, or mutates phase state.
    """
    from hl_observer.backtest.walk_forward import walk_forward_safety_receipt

    walk_valid = walk_forward_safety_receipt(walk_forward_result).get("status") == "PROVEN"
    phase_valid = phase_state_safety_receipt(phase_state).get("status") == "PROVEN"
    valid = walk_valid and phase_valid
    return _phase_base(
        "PROVEN" if valid else "REJECTED",
        verdict="WALK_FORWARD_TO_PHASE_BOUNDARY_SAFE" if valid else "WALK_FORWARD_TO_PHASE_BOUNDARY_UNSAFE",
        walk_forward_status="PROVEN" if walk_valid else "REJECTED",
        phase_state_status="PROVEN" if phase_valid else "REJECTED",
        promotion="DISABLED_UNTIL_REVIEW",
        fail_closed=not valid,
    )


def native_venue_to_phase_boundary_receipt(
    venue_result: Any,
    phase_state: Any,
) -> dict[str, Any]:
    """Join a native venue declaration to phase state without enabling execution."""
    from hl_observer.venues.hyperliquid import venue_capability_safety_receipt

    venue = venue_capability_safety_receipt(venue_result)
    phase = phase_state_safety_receipt(phase_state)
    valid = (
        venue.get("status") == "PROVEN"
        and venue.get("paper_read_only") is True
        and venue.get("real_execution") is False
        and venue.get("network_execution") is False
        and venue.get("fail_closed") is False
        and phase.get("status") == "PROVEN"
        and phase.get("paper_read_only") is True
        and phase.get("real_execution") is False
        and phase.get("phase_mutation") is False
        and phase.get("fail_closed") is False
    )
    return _phase_base(
        "PROVEN" if valid else "REJECTED",
        verdict="NATIVE_VENUE_TO_PHASE_BOUNDARY_SAFE" if valid else "NATIVE_VENUE_TO_PHASE_BOUNDARY_REJECTED",
        venue_status=venue.get("status"),
        phase_status=phase.get("status"),
        network_execution=False,
        promotion="DISABLED_UNTIL_REVIEW",
        fail_closed=not valid,
    )


def phase_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and field in row and row[field] not in (None, "")
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_FIELD_PRESENT" if valid else "PHASE_FIELD_MISSING", field=field, fail_closed=not valid)


def phase_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and field in row and row[field] is not None
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_FIELD_NON_NULL" if valid else "PHASE_FIELD_NULL", field=field, fail_closed=not valid)


def phase_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    value = row.get(field) if isinstance(row, Mapping) else None
    bool_is_int = expected_type is int and isinstance(value, bool)
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and isinstance(expected_type, type) and isinstance(value, expected_type) and not bool_is_int
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_FIELD_TYPE_VALID" if valid else "PHASE_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def phase_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _phase_finite(value)
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_VALUE_FINITE" if valid else "PHASE_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def phase_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _phase_integer(event_ts_ms) and _phase_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_EVENT_WITHIN_CUTOFF" if valid else "PHASE_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def phase_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _phase_integer(event_ts_ms) and _phase_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_EVENT_AGE_VALID" if valid else "PHASE_EVENT_TOO_OLD", fail_closed=not valid)


def phase_duplicate_receipt(*, event_ids: Iterable[Any]) -> dict[str, Any]:
    values = list(event_ids)
    valid = bool(values) and all(isinstance(value, str) and value.strip() for value in values) and len(values) == len(set(values))
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_EVENTS_UNIQUE" if valid else "PHASE_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def phase_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _phase_integer(attempts) and _phase_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_RETRY_BOUNDED" if valid else "PHASE_RETRY_UNSAFE", fail_closed=not valid)


def phase_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    values = list(outputs)
    valid = bool(values) and len({canonical_json(value) for value in values}) == 1
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_REPLAY_DETERMINISTIC" if valid else "PHASE_REPLAY_DIVERGED", fail_closed=not valid)


def phase_stage_order_receipt(*, phase: Any, analysis_stage: Any, drained: bool) -> dict[str, Any]:
    valid = phase == "ANALYZE" and analysis_stage in VALID_ANALYSIS_STAGES - {None} and drained is True
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_STAGE_AFTER_DRAIN" if valid else "PHASE_STAGE_BEFORE_DRAIN", fail_closed=not valid)


def phase_collect_authorization_receipt(*, phase: Any, automatic: bool, authorized: bool) -> dict[str, Any]:
    valid = phase == "COLLECT" and isinstance(automatic, bool) and automatic is False or (phase == "COLLECT" and automatic is True and authorized is True)
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_COLLECT_AUTHORIZED" if valid else "PHASE_COLLECT_UNAUTHORIZED", fail_closed=not valid)


def phase_request_replay_receipt(*, request_ids: Sequence[Any], accepted_request_ids: Sequence[Any]) -> dict[str, Any]:
    requests = list(request_ids)
    accepted = list(accepted_request_ids)
    valid = bool(requests) and len(requests) == len(set(requests)) and len(accepted) == len(set(accepted)) and set(accepted).issubset(requests)
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_REQUESTS_IDEMPOTENT" if valid else "PHASE_REQUEST_REPLAYED", fail_closed=not valid)


def phase_epoch_receipt(*, observed_epoch: Any, current_epoch: Any) -> dict[str, Any]:
    valid = _phase_integer(observed_epoch) and _phase_integer(current_epoch) and observed_epoch == current_epoch
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_EPOCH_CURRENT" if valid else "PHASE_EPOCH_STALE", fail_closed=not valid)


def phase_hash_receipt(*, expected_sha: Any, actual_sha: Any) -> dict[str, Any]:
    valid = _phase_sha(expected_sha) and _phase_sha(actual_sha) and expected_sha == actual_sha
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_SHA_MATCH" if valid else "PHASE_SHA_MISMATCH", fail_closed=not valid)


def phase_lease_receipt(*, worker_id: Any, lease_owner: Any, lease_expires_at_ms: Any, now_ms: Any) -> dict[str, Any]:
    valid = isinstance(worker_id, str) and bool(worker_id.strip()) and worker_id == lease_owner and _phase_integer(lease_expires_at_ms) and _phase_integer(now_ms) and now_ms < lease_expires_at_ms
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_LEASE_ACTIVE" if valid else "PHASE_LEASE_EXPIRED_OR_MISMATCHED", fail_closed=not valid)


def phase_single_owner_receipt(*, owner_ids: Sequence[Any]) -> dict[str, Any]:
    owners = list(owner_ids)
    valid = len(owners) == 1 and isinstance(owners[0], str) and bool(owners[0].strip())
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_SINGLE_OWNER" if valid else "PHASE_SPLIT_BRAIN", fail_closed=not valid)


def phase_checkpoint_receipt(*, checkpoint: Mapping[str, Any], required_fields: Sequence[str]) -> dict[str, Any]:
    required = list(required_fields)
    valid = isinstance(checkpoint, Mapping) and bool(required) and all(isinstance(field, str) and checkpoint.get(field) not in (None, "") for field in required) and checkpoint.get("saved") is True
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_CHECKPOINT_COMPLETE" if valid else "PHASE_CHECKPOINT_PARTIAL", fail_closed=not valid)


def phase_runner_receipt(*, runner_label: Any) -> dict[str, Any]:
    normalized = runner_label.strip().lower() if isinstance(runner_label, str) else ""
    valid = bool(normalized) and "self-hosted" not in normalized and "self_hosted" not in normalized and "localhost" not in normalized and normalized in {"ubuntu-latest", "windows-latest", "macos-latest", "github-hosted"}
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_GITHUB_HOSTED" if valid else "PHASE_RUNNER_FORBIDDEN", fail_closed=not valid)


def phase_done_coverage_receipt(*, phase: Any, analysis_stage: Any, coverage_status: Any, required_proofs: Sequence[Any], completed_proofs: Sequence[Any]) -> dict[str, Any]:
    required = set(required_proofs)
    completed = set(completed_proofs)
    valid = phase == "ANALYZE" and analysis_stage == "DONE" and coverage_status == "PROVEN" and bool(required) and required.issubset(completed)
    return _phase_base("PROVEN" if valid else "REJECTED", verdict="PHASE_DONE_COVERAGE_COMPLETE" if valid else "PHASE_DONE_WITHOUT_COVERAGE", fail_closed=not valid)


__all__ = [
    "SCHEMA_VERSION", "VALID_PHASES", "VALID_ANALYSIS_STAGES", "AlinaPhaseState",
    "canonical_json", "sha256_json", "parse_iso_utc", "validate_phase_state",
    "phase_state_safety_receipt", "phase_required_field_receipt", "phase_null_field_receipt",
    "phase_field_type_receipt", "phase_finite_receipt", "phase_cutoff_receipt", "phase_age_receipt",
    "phase_duplicate_receipt", "phase_retry_receipt", "phase_replay_receipt", "phase_stage_order_receipt",
    "phase_collect_authorization_receipt", "phase_request_replay_receipt", "phase_epoch_receipt",
    "phase_hash_receipt", "phase_lease_receipt", "phase_single_owner_receipt", "phase_checkpoint_receipt",
    "phase_runner_receipt", "phase_done_coverage_receipt",
    "walk_forward_to_phase_boundary_receipt", "native_venue_to_phase_boundary_receipt",
]
