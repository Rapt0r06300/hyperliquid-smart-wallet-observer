"""Deterministic cross-repository dispatch receipts for Alina SmartFlow."""
from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from hl_observer.control_plane.phase_state import canonical_json, parse_iso_utc, sha256_json

DISPATCH_STATUSES = frozenset({"DISPATCHED", "RUNNING", "COMPLETE", "FAILED", "BLOCKED", "CANCELLED"})
TERMINAL_DISPATCH_STATUSES = frozenset({"COMPLETE", "FAILED", "BLOCKED", "CANCELLED"})

_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def generate_request_id(
    operator_intent: str,
    main_code_sha: str,
    requested_phase_epoch: int,
    campaign_kind: str,
    normalized_config: Mapping[str, Any],
) -> str:
    if not _is_positive_int(requested_phase_epoch):
        raise ValueError("requested_phase_epoch must be a positive integer")
    payload = {
        "operator_intent": operator_intent,
        "main_code_sha": main_code_sha,
        "requested_phase_epoch": requested_phase_epoch,
        "campaign_kind": campaign_kind,
        "config": dict(normalized_config),
    }
    return sha256_json(payload)


@dataclass(frozen=True)
class DispatchReceipt:
    request_id: str
    campaign_id: str
    main_code_sha: str
    dataset_repo_sha: str
    creation_phase: str
    phase_epoch: int
    source_collection_epoch: int | None
    workflow_run_id: str | None
    dispatched_at_utc: str
    status: str = "DISPATCHED"
    terminal_at_utc: str | None = None
    failure_code: str | None = None
    terminal_evidence_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def content_digest(self) -> str:
        return sha256_json(self.to_dict())

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> DispatchReceipt:
        allowed = set(cls.__dataclass_fields__)
        unknown = set(raw) - allowed
        if unknown:
            raise ValueError(f"Unknown dispatch receipt fields: {sorted(unknown)}")
        payload = dict(raw)
        # v1 receipts had no lifecycle fields. Preserve their meaning while
        # upgrading them into the explicit v2 state machine.
        if "status" not in payload:
            payload["status"] = "COMPLETE" if payload.get("terminal_evidence_digest") else "DISPATCHED"
        if payload.get("status") == "COMPLETE" and "terminal_at_utc" not in payload:
            payload["terminal_at_utc"] = payload.get("dispatched_at_utc")
        return cls(**payload)


def validate_dispatch_receipt(receipt: DispatchReceipt) -> None:
    """Fail closed on incomplete or contradictory cross-repository identity."""
    if not receipt.request_id or not receipt.campaign_id:
        raise ValueError("dispatch receipt requires request_id and campaign_id")
    if not _SHA40.fullmatch(str(receipt.main_code_sha or "").lower()):
        raise ValueError("dispatch receipt requires an exact main repository SHA")
    if not _SHA40.fullmatch(str(receipt.dataset_repo_sha or "").lower()):
        raise ValueError("dispatch receipt requires an exact dataset repository SHA")
    if receipt.creation_phase not in {"IDLE", "COLLECT", "ANALYZE"}:
        raise ValueError("dispatch receipt has invalid creation phase")
    if not _is_positive_int(receipt.phase_epoch):
        raise ValueError("dispatch receipt has invalid phase epoch")
    if receipt.creation_phase == "ANALYZE":
        if not _is_positive_int(receipt.source_collection_epoch):
            raise ValueError("analysis dispatch requires source collection epoch")
    elif receipt.source_collection_epoch is not None:
        raise ValueError("non-analysis dispatch must not bind a source collection epoch")
    parse_iso_utc(receipt.dispatched_at_utc)
    if receipt.status not in DISPATCH_STATUSES:
        raise ValueError(f"dispatch receipt has invalid status: {receipt.status}")
    is_terminal = receipt.status in TERMINAL_DISPATCH_STATUSES
    if is_terminal != (receipt.terminal_at_utc is not None):
        raise ValueError("terminal dispatch status requires terminal_at_utc, and non-terminal status forbids it")
    if receipt.terminal_at_utc is not None:
        parse_iso_utc(receipt.terminal_at_utc)
    if receipt.status == "FAILED" and not receipt.failure_code:
        raise ValueError("failed dispatch receipt requires failure_code")
    if receipt.status != "FAILED" and receipt.failure_code is not None:
        raise ValueError("failure_code is only valid for FAILED dispatches")
    if receipt.status == "COMPLETE" and not _SHA256.fullmatch(str(receipt.terminal_evidence_digest or "").lower()):
        raise ValueError("complete dispatch receipt requires an exact terminal evidence digest")
    if receipt.status != "COMPLETE" and receipt.terminal_evidence_digest is not None:
        raise ValueError("terminal evidence digest is only valid for COMPLETE dispatches")


def _dispatch_base(status: str, **values: Any) -> dict[str, Any]:
    """Return paper/read-only dispatch evidence without dispatching anything."""
    return {"status": status, "paper_read_only": True, "real_execution": False, "dispatch_mutation": False, "closure_allowed": False, **values}


def _dispatch_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _dispatch_finite(value: Any) -> bool:
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _dispatch_sha(value: Any, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and all(ch in "0123456789abcdef" for ch in value)


def dispatch_state_safety_receipt(receipt: Any) -> dict[str, Any]:
    try:
        candidate = receipt if isinstance(receipt, DispatchReceipt) else DispatchReceipt.from_dict(receipt)
        validate_dispatch_receipt(candidate)
    except (TypeError, ValueError):
        return _dispatch_base("REJECTED", verdict="DISPATCH_RECEIPT_INVALID", fail_closed=True)
    return _dispatch_base("PROVEN", verdict="DISPATCH_RECEIPT_VALID", phase=candidate.creation_phase, epoch=candidate.phase_epoch, fail_closed=False)


def dispatch_to_campaign_boundary_receipt(dispatch_result: Any, campaign_manifest: Any) -> dict[str, Any]:
    """Admit a dispatch receipt to a campaign without dispatching or mutating it."""
    from hl_observer.control_plane.resumable_campaign import campaign_state_safety_receipt

    dispatch = dispatch_state_safety_receipt(dispatch_result)
    campaign = campaign_state_safety_receipt(campaign_manifest)
    valid = (
        dispatch.get("status") == "PROVEN"
        and dispatch.get("paper_read_only") is True
        and dispatch.get("real_execution") is False
        and dispatch.get("dispatch_mutation") is False
        and dispatch.get("fail_closed") is False
        and campaign.get("status") == "PROVEN"
        and campaign.get("paper_read_only") is True
        and campaign.get("real_execution") is False
        and campaign.get("manifest_mutation") is False
        and campaign.get("fail_closed") is False
    )
    return _dispatch_base(
        "PROVEN" if valid else "REJECTED",
        verdict="DISPATCH_CAMPAIGN_BOUNDARY_SAFE" if valid else "DISPATCH_CAMPAIGN_BOUNDARY_REJECTED",
        dispatch_status=dispatch.get("status"),
        campaign_status=campaign.get("status"),
        dispatch_mutation=False,
        manifest_mutation=False,
        phase_mutation=False,
        promotion="DISABLED_UNTIL_REVIEW",
        fail_closed=not valid,
    )


def native_venue_to_dispatch_boundary_receipt(
    venue_result: Any,
    dispatch_result: Any,
) -> dict[str, Any]:
    """Admit OKX public capabilities to dispatch evidence without dispatching."""
    from hl_observer.venues.okx import venue_capability_safety_receipt

    venue = venue_capability_safety_receipt(venue_result)
    dispatch = dispatch_state_safety_receipt(dispatch_result)
    valid = (
        venue.get("status") == "PROVEN"
        and venue.get("paper_read_only") is True
        and venue.get("real_execution") is False
        and venue.get("network_execution") is False
        and dispatch.get("status") == "PROVEN"
        and dispatch.get("paper_read_only") is True
        and dispatch.get("real_execution") is False
        and dispatch.get("dispatch_mutation") is False
        and dispatch.get("fail_closed") is False
    )
    return _dispatch_base(
        "PROVEN" if valid else "REJECTED",
        verdict="NATIVE_VENUE_DISPATCH_BOUNDARY_SAFE" if valid else "NATIVE_VENUE_DISPATCH_BOUNDARY_REJECTED",
        venue_status=venue.get("status"),
        dispatch_status=dispatch.get("status"),
        network_execution=False,
        dispatch_mutation=False,
        promotion="DISABLED_UNTIL_REVIEW",
        fail_closed=not valid,
    )


def dispatch_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and field in row and row[field] not in (None, "")
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_FIELD_PRESENT" if valid else "DISPATCH_FIELD_MISSING", field=field, fail_closed=not valid)


def dispatch_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and field in row and row[field] is not None
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_FIELD_NON_NULL" if valid else "DISPATCH_FIELD_NULL", field=field, fail_closed=not valid)


def dispatch_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    value = row.get(field) if isinstance(row, Mapping) else None
    bool_is_int = expected_type is int and isinstance(value, bool)
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and isinstance(expected_type, type) and isinstance(value, expected_type) and not bool_is_int
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_FIELD_TYPE_VALID" if valid else "DISPATCH_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def dispatch_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _dispatch_finite(value)
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_VALUE_FINITE" if valid else "DISPATCH_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def dispatch_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _dispatch_integer(event_ts_ms) and _dispatch_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_EVENT_WITHIN_CUTOFF" if valid else "DISPATCH_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def dispatch_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _dispatch_integer(event_ts_ms) and _dispatch_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_EVENT_AGE_VALID" if valid else "DISPATCH_EVENT_TOO_OLD", fail_closed=not valid)


def dispatch_duplicate_receipt(*, event_ids: Iterable[Any]) -> dict[str, Any]:
    values = list(event_ids)
    valid = bool(values) and all(isinstance(value, str) and value.strip() for value in values) and len(values) == len(set(values))
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_EVENTS_UNIQUE" if valid else "DISPATCH_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def dispatch_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _dispatch_integer(attempts) and _dispatch_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_RETRY_BOUNDED" if valid else "DISPATCH_RETRY_UNSAFE", fail_closed=not valid)


def dispatch_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    values = list(outputs)
    valid = bool(values) and len({canonical_json(value) for value in values}) == 1
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_REPLAY_DETERMINISTIC" if valid else "DISPATCH_REPLAY_DIVERGED", fail_closed=not valid)


def dispatch_stage_order_receipt(*, creation_phase: Any, status: Any, phase_barrier: bool) -> dict[str, Any]:
    valid = creation_phase in {"COLLECT", "ANALYZE"} and status in DISPATCH_STATUSES and phase_barrier is True
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_PHASE_BARRIER" if valid else "DISPATCH_PHASE_BARRIER_MISSING", fail_closed=not valid)


def dispatch_collect_authorization_receipt(*, creation_phase: Any, automatic: bool, authorized: bool) -> dict[str, Any]:
    valid = creation_phase == "COLLECT" and isinstance(automatic, bool) and ((automatic is False and authorized is False) or (automatic is True and authorized is True))
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_COLLECT_AUTHORIZED" if valid else "DISPATCH_COLLECT_UNAUTHORIZED", fail_closed=not valid)


def dispatch_request_replay_receipt(*, request_ids: Sequence[Any], accepted_request_ids: Sequence[Any]) -> dict[str, Any]:
    requests = list(request_ids)
    accepted = list(accepted_request_ids)
    valid = bool(requests) and len(requests) == len(set(requests)) and len(accepted) == len(set(accepted)) and set(accepted).issubset(requests)
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_REQUESTS_IDEMPOTENT" if valid else "DISPATCH_REQUEST_REPLAYED", fail_closed=not valid)


def dispatch_epoch_receipt(*, observed_epoch: Any, current_epoch: Any) -> dict[str, Any]:
    valid = _dispatch_integer(observed_epoch) and _dispatch_integer(current_epoch) and observed_epoch == current_epoch
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_EPOCH_CURRENT" if valid else "DISPATCH_EPOCH_STALE", fail_closed=not valid)


def dispatch_hash_receipt(*, expected_sha: Any, actual_sha: Any, length: int = 40) -> dict[str, Any]:
    valid = _dispatch_sha(expected_sha, length) and _dispatch_sha(actual_sha, length) and expected_sha == actual_sha
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_SHA_MATCH" if valid else "DISPATCH_SHA_MISMATCH", fail_closed=not valid)


def dispatch_lease_receipt(*, worker_id: Any, lease_owner: Any, lease_expires_at_ms: Any, now_ms: Any) -> dict[str, Any]:
    valid = isinstance(worker_id, str) and bool(worker_id.strip()) and worker_id == lease_owner and _dispatch_integer(lease_expires_at_ms) and _dispatch_integer(now_ms) and now_ms < lease_expires_at_ms
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_LEASE_ACTIVE" if valid else "DISPATCH_LEASE_EXPIRED_OR_MISMATCHED", fail_closed=not valid)


def dispatch_single_owner_receipt(*, owner_ids: Sequence[Any]) -> dict[str, Any]:
    owners = list(owner_ids)
    valid = len(owners) == 1 and isinstance(owners[0], str) and bool(owners[0].strip())
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_SINGLE_OWNER" if valid else "DISPATCH_SPLIT_BRAIN", fail_closed=not valid)


def dispatch_checkpoint_receipt(*, checkpoint: Mapping[str, Any], required_fields: Sequence[str]) -> dict[str, Any]:
    required = list(required_fields)
    valid = isinstance(checkpoint, Mapping) and bool(required) and all(isinstance(field, str) and checkpoint.get(field) not in (None, "") for field in required) and checkpoint.get("saved") is True
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_CHECKPOINT_COMPLETE" if valid else "DISPATCH_CHECKPOINT_PARTIAL", fail_closed=not valid)


def dispatch_runner_receipt(*, runner_label: Any) -> dict[str, Any]:
    normalized = runner_label.strip().lower() if isinstance(runner_label, str) else ""
    valid = bool(normalized) and "self-hosted" not in normalized and "self_hosted" not in normalized and "localhost" not in normalized and normalized in {"ubuntu-latest", "windows-latest", "macos-latest", "github-hosted"}
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_GITHUB_HOSTED" if valid else "DISPATCH_RUNNER_FORBIDDEN", fail_closed=not valid)


def dispatch_done_coverage_receipt(*, status: Any, coverage_status: Any, required_proofs: Sequence[Any], completed_proofs: Sequence[Any]) -> dict[str, Any]:
    required = set(required_proofs)
    completed = set(completed_proofs)
    valid = status == "COMPLETE" and coverage_status == "PROVEN" and bool(required) and required.issubset(completed)
    return _dispatch_base("PROVEN" if valid else "REJECTED", verdict="DISPATCH_DONE_COVERAGE_COMPLETE" if valid else "DISPATCH_DONE_WITHOUT_COVERAGE", fail_closed=not valid)
