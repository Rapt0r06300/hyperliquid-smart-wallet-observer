"""Atomic, fail-closed Phase Controller for Alina SmartFlow."""
from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from hl_observer.control_plane.phase_state import (
    AlinaPhaseState,
    _now,
    canonical_json,
    parse_iso_utc,
    validate_phase_state,
)


@dataclass(frozen=True)
class TransitionReceipt:
    request_id: str
    previous_epoch: int
    new_epoch: int
    previous_phase: str
    new_phase: str
    transitioned_at_utc: str
    state_digest: str
    state: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PhaseController:
    """Manages atomic, fail-closed transitions for AlinaPhaseState."""

    def __init__(self, state_file_path: Path | str | None = None, initial_state: AlinaPhaseState | None = None):
        self.state_file_path = Path(state_file_path) if state_file_path else None
        if initial_state:
            validate_phase_state(initial_state)
            self._state = initial_state
        elif self.state_file_path and self.state_file_path.exists():
            self._state = self._load_from_disk()
        else:
            self._state = AlinaPhaseState()
            if self.state_file_path:
                self._save_to_disk()

    @property
    def current_state(self) -> AlinaPhaseState:
        # Never expose mutable internal state: callers must use a validated
        # transition instead of changing the control plane without a receipt.
        return AlinaPhaseState(**self._state.to_dict())

    def _ensure_monotonic_request_time(self, now_utc: str) -> None:
        """Reject a phase request that moves the control plane backwards."""
        # A freshly created IDLE state only records file creation time; it is
        # not an operator transition and must not prevent replaying a pinned
        # historical request in tests or an offline paper campaign.
        if self._state.phase == "IDLE" and self._state.request_id is None:
            return
        requested = parse_iso_utc(now_utc)
        current = parse_iso_utc(self._state.requested_at_utc)
        if requested < current:
            raise ValueError(
                "phase request timestamp precedes the current state timestamp"
            )

    def _load_from_disk(self) -> AlinaPhaseState:
        if not self.state_file_path or not self.state_file_path.exists():
            raise FileNotFoundError("Phase state file does not exist")
        with open(self.state_file_path, encoding="utf-8") as f:
            data = json.load(f)
        return AlinaPhaseState.from_dict(data)

    def _save_to_disk(self) -> None:
        if not self.state_file_path:
            return
        self.state_file_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix=f".{self.state_file_path.name}.", dir=self.state_file_path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(self._state.to_dict(), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, self.state_file_path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

    def transition_to_collect(
        self,
        *,
        request_id: str,
        requested_by: str = "operator",
        now_utc: str | None = None,
    ) -> TransitionReceipt:
        now = now_utc or _now()

        # Idempotency check
        if self._state.request_id == request_id and self._state.phase == "COLLECT":
            return TransitionReceipt(
                request_id=request_id,
                previous_epoch=self._state.epoch,
                new_epoch=self._state.epoch,
                previous_phase="COLLECT",
                new_phase="COLLECT",
                transitioned_at_utc=self._state.requested_at_utc,
                state_digest=self._state.content_digest(),
                state=self._state.to_dict(),
            )

        self._ensure_monotonic_request_time(now)

        if self._state.phase not in ("IDLE", "COLLECT", "ANALYZE"):
            raise ValueError(f"Cannot transition to COLLECT from phase {self._state.phase}")

        prev_epoch = self._state.epoch
        prev_phase = self._state.phase
        new_epoch = prev_epoch + 1 if prev_phase != "COLLECT" else prev_epoch

        new_state = AlinaPhaseState(
            schema_version=1,
            phase="COLLECT",
            epoch=new_epoch,
            requested_at_utc=now,
            collection_started_at_utc=now,
            collection_cutoff_at_utc=None,
            source_collection_epoch=None,
            analysis_stage=None,
            requested_by=requested_by,
            request_id=request_id,
        )

        validate_phase_state(new_state)
        self._state = new_state
        self._save_to_disk()

        return TransitionReceipt(
            request_id=request_id,
            previous_epoch=prev_epoch,
            new_epoch=new_epoch,
            previous_phase=prev_phase,
            new_phase="COLLECT",
            transitioned_at_utc=now,
            state_digest=new_state.content_digest(),
            state=new_state.to_dict(),
        )

    def transition_to_analyze(
        self,
        *,
        request_id: str,
        requested_by: str = "operator",
        initial_stage: str = "DRAIN",
        now_utc: str | None = None,
    ) -> TransitionReceipt:
        now = now_utc or _now()

        # Idempotency check
        if self._state.request_id == request_id and self._state.phase == "ANALYZE":
            return TransitionReceipt(
                request_id=request_id,
                previous_epoch=self._state.epoch,
                new_epoch=self._state.epoch,
                previous_phase="ANALYZE",
                new_phase="ANALYZE",
                transitioned_at_utc=self._state.requested_at_utc,
                state_digest=self._state.content_digest(),
                state=self._state.to_dict(),
            )

        self._ensure_monotonic_request_time(now)

        if self._state.phase != "COLLECT":
            raise ValueError(f"Transition to ANALYZE requires phase COLLECT, current: {self._state.phase}")
        if initial_stage != "DRAIN":
            raise ValueError("ANALYZE must begin at DRAIN")

        prev_epoch = self._state.epoch
        finished_collection_epoch = prev_epoch
        new_epoch = prev_epoch + 1

        new_state = AlinaPhaseState(
            schema_version=1,
            phase="ANALYZE",
            epoch=new_epoch,
            requested_at_utc=now,
            collection_started_at_utc=self._state.collection_started_at_utc,
            collection_cutoff_at_utc=now,
            source_collection_epoch=finished_collection_epoch,
            analysis_stage=initial_stage,
            requested_by=requested_by,
            request_id=request_id,
        )

        validate_phase_state(new_state)
        self._state = new_state
        self._save_to_disk()

        return TransitionReceipt(
            request_id=request_id,
            previous_epoch=prev_epoch,
            new_epoch=new_epoch,
            previous_phase="COLLECT",
            new_phase="ANALYZE",
            transitioned_at_utc=now,
            state_digest=new_state.content_digest(),
            state=new_state.to_dict(),
        )

    def transition_to_idle(
        self,
        *,
        request_id: str,
        requested_by: str = "operator",
        now_utc: str | None = None,
    ) -> TransitionReceipt:
        now = now_utc or _now()

        if self._state.request_id == request_id and self._state.phase == "IDLE":
            return TransitionReceipt(
                request_id=request_id,
                previous_epoch=self._state.epoch,
                new_epoch=self._state.epoch,
                previous_phase="IDLE",
                new_phase="IDLE",
                transitioned_at_utc=self._state.requested_at_utc,
                state_digest=self._state.content_digest(),
                state=self._state.to_dict(),
            )

        self._ensure_monotonic_request_time(now)

        prev_epoch = self._state.epoch
        prev_phase = self._state.phase
        new_epoch = prev_epoch + 1 if prev_phase != "IDLE" else prev_epoch

        new_state = AlinaPhaseState(
            schema_version=1,
            phase="IDLE",
            epoch=new_epoch,
            requested_at_utc=now,
            collection_started_at_utc=None,
            collection_cutoff_at_utc=None,
            source_collection_epoch=None,
            analysis_stage=None,
            requested_by=requested_by,
            request_id=request_id,
        )

        validate_phase_state(new_state)
        self._state = new_state
        self._save_to_disk()

        return TransitionReceipt(
            request_id=request_id,
            previous_epoch=prev_epoch,
            new_epoch=new_epoch,
            previous_phase=prev_phase,
            new_phase="IDLE",
            transitioned_at_utc=now,
            state_digest=new_state.content_digest(),
            state=new_state.to_dict(),
        )

    def advance_analysis_stage(self, stage: str) -> AlinaPhaseState:
        if self._state.phase != "ANALYZE":
            raise ValueError(f"Cannot advance analysis_stage when phase is {self._state.phase}")
        ordered = ("DRAIN", "QUALITY", "REPLAY", "BACKTEST", "OOS", "FORWARD_PAPER", "PNL_PROOF", "SCOREBOARD", "DONE")
        if stage not in ordered:
            raise ValueError(f"Unknown analysis stage: {stage}")
        current = self._state.analysis_stage
        if current not in ordered:
            raise ValueError(f"Invalid current analysis stage: {current}")
        if ordered.index(stage) < ordered.index(current):
            raise ValueError(f"Analysis stage regression: {current}->{stage}")
        if ordered.index(stage) > ordered.index(current) + 1:
            raise ValueError(f"Analysis stage skip is forbidden: {current}->{stage}")
        new_state = AlinaPhaseState(
            schema_version=self._state.schema_version,
            phase="ANALYZE",
            epoch=self._state.epoch,
            requested_at_utc=self._state.requested_at_utc,
            collection_started_at_utc=self._state.collection_started_at_utc,
            collection_cutoff_at_utc=self._state.collection_cutoff_at_utc,
            source_collection_epoch=self._state.source_collection_epoch,
            analysis_stage=stage,
            requested_by=self._state.requested_by,
            request_id=self._state.request_id,
        )
        validate_phase_state(new_state)
        self._state = new_state
        self._save_to_disk()
        return self._state


def _controller_base(status: str, **values: Any) -> dict[str, Any]:
    """Return a paper/read-only controller evidence receipt."""
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "phase_mutation": False,
        "closure_allowed": False,
        **values,
    }


def _controller_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _controller_finite(value: Any) -> bool:
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _controller_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def controller_state_safety_receipt(state: Any) -> dict[str, Any]:
    try:
        candidate = state if isinstance(state, AlinaPhaseState) else AlinaPhaseState.from_dict(state)
        validate_phase_state(candidate)
    except (TypeError, ValueError):
        return _controller_base("REJECTED", verdict="CONTROLLER_STATE_INVALID", fail_closed=True)
    return _controller_base("PROVEN", verdict="CONTROLLER_STATE_VALID", phase=candidate.phase, epoch=candidate.epoch, fail_closed=False)


def economic_freeze_to_controller_boundary_receipt(
    freeze_result: Any,
    controller_state: Any,
) -> dict[str, Any]:
    """Join an immutable economic freeze to the controller boundary.

    The join validates admissibility only. It never advances the controller,
    rewrites a freeze, promotes a champion or enables real execution.
    """
    from hl_observer.simulation.economic_freeze_registry import economic_freeze_safety_receipt

    freeze_valid = economic_freeze_safety_receipt(freeze_result).get("status") == "PROVEN"
    controller_valid = controller_state_safety_receipt(controller_state).get("status") == "PROVEN"
    valid = freeze_valid and controller_valid
    return _controller_base(
        "PROVEN" if valid else "REJECTED",
        verdict="ECONOMIC_FREEZE_TO_CONTROLLER_SAFE" if valid else "ECONOMIC_FREEZE_TO_CONTROLLER_UNSAFE",
        freeze_status="PROVEN" if freeze_valid else "REJECTED",
        controller_status="PROVEN" if controller_valid else "REJECTED",
        promotion="DISABLED_UNTIL_REVIEW",
        fail_closed=not valid,
    )


def controller_to_dispatch_boundary_receipt(
    controller_state: Any,
    dispatch_result: Any,
) -> dict[str, Any]:
    """Admit a controller state to dispatch only when phase and epoch match."""
    from hl_observer.control_plane.dispatch_receipt import dispatch_state_safety_receipt

    controller = controller_state_safety_receipt(controller_state)
    dispatch = dispatch_state_safety_receipt(dispatch_result)
    valid = (
        controller.get("status") == "PROVEN"
        and controller.get("paper_read_only") is True
        and controller.get("real_execution") is False
        and controller.get("phase_mutation") is False
        and controller.get("fail_closed") is False
        and dispatch.get("status") == "PROVEN"
        and dispatch.get("paper_read_only") is True
        and dispatch.get("real_execution") is False
        and dispatch.get("dispatch_mutation") is False
        and dispatch.get("fail_closed") is False
        and controller.get("phase") == dispatch.get("phase")
        and controller.get("epoch") == dispatch.get("epoch")
    )
    return _controller_base(
        "PROVEN" if valid else "REJECTED",
        verdict="CONTROLLER_DISPATCH_BOUNDARY_SAFE" if valid else "CONTROLLER_DISPATCH_BOUNDARY_REJECTED",
        controller_status=controller.get("status"),
        dispatch_status=dispatch.get("status"),
        phase_match=controller.get("phase") == dispatch.get("phase"),
        epoch_match=controller.get("epoch") == dispatch.get("epoch"),
        dispatch_mutation=False,
        promotion="DISABLED_UNTIL_REVIEW",
        fail_closed=not valid,
    )


def native_venue_to_controller_boundary_receipt(
    venue_result: Any,
    controller_state: Any,
) -> dict[str, Any]:
    """Admit Binance public capabilities to the controller read-only boundary."""
    from hl_observer.venues.binance import venue_capability_safety_receipt

    venue = venue_capability_safety_receipt(venue_result)
    controller = controller_state_safety_receipt(controller_state)
    valid = (
        venue.get("status") == "PROVEN"
        and venue.get("paper_read_only") is True
        and venue.get("real_execution") is False
        and venue.get("network_execution") is False
        and controller.get("status") == "PROVEN"
        and controller.get("paper_read_only") is True
        and controller.get("real_execution") is False
        and controller.get("phase_mutation") is False
        and controller.get("fail_closed") is False
    )
    return _controller_base(
        "PROVEN" if valid else "REJECTED",
        verdict="NATIVE_VENUE_CONTROLLER_BOUNDARY_SAFE" if valid else "NATIVE_VENUE_CONTROLLER_BOUNDARY_REJECTED",
        venue_status=venue.get("status"),
        controller_status=controller.get("status"),
        network_execution=False,
        phase_mutation=False,
        promotion="DISABLED_UNTIL_REVIEW",
        fail_closed=not valid,
    )


def controller_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and field in row and row[field] not in (None, "")
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_FIELD_PRESENT" if valid else "CONTROLLER_FIELD_MISSING", field=field, fail_closed=not valid)


def controller_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and field in row and row[field] is not None
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_FIELD_NON_NULL" if valid else "CONTROLLER_FIELD_NULL", field=field, fail_closed=not valid)


def controller_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    value = row.get(field) if isinstance(row, Mapping) else None
    bool_is_int = expected_type is int and isinstance(value, bool)
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and isinstance(expected_type, type) and isinstance(value, expected_type) and not bool_is_int
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_FIELD_TYPE_VALID" if valid else "CONTROLLER_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def controller_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _controller_finite(value)
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_VALUE_FINITE" if valid else "CONTROLLER_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def controller_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _controller_integer(event_ts_ms) and _controller_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_EVENT_WITHIN_CUTOFF" if valid else "CONTROLLER_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def controller_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _controller_integer(event_ts_ms) and _controller_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_EVENT_AGE_VALID" if valid else "CONTROLLER_EVENT_TOO_OLD", fail_closed=not valid)


def controller_duplicate_receipt(*, event_ids: Iterable[Any]) -> dict[str, Any]:
    values = list(event_ids)
    valid = bool(values) and all(isinstance(value, str) and value.strip() for value in values) and len(values) == len(set(values))
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_EVENTS_UNIQUE" if valid else "CONTROLLER_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def controller_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _controller_integer(attempts) and _controller_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_RETRY_BOUNDED" if valid else "CONTROLLER_RETRY_UNSAFE", fail_closed=not valid)


def controller_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    values = list(outputs)
    valid = bool(values) and len({canonical_json(value) for value in values}) == 1
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_REPLAY_DETERMINISTIC" if valid else "CONTROLLER_REPLAY_DIVERGED", fail_closed=not valid)


def controller_stage_order_receipt(*, phase: Any, analysis_stage: Any, drained: bool) -> dict[str, Any]:
    valid = phase == "ANALYZE" and analysis_stage in {"DRAIN", "QUALITY", "REPLAY", "BACKTEST", "OOS", "FORWARD_PAPER", "PNL_PROOF", "SCOREBOARD", "DONE"} and drained is True
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_STAGE_AFTER_DRAIN" if valid else "CONTROLLER_STAGE_BEFORE_DRAIN", fail_closed=not valid)


def controller_collect_authorization_receipt(*, phase: Any, automatic: bool, authorized: bool) -> dict[str, Any]:
    valid = phase == "COLLECT" and isinstance(automatic, bool) and ((automatic is False and authorized is False) or (automatic is True and authorized is True))
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_COLLECT_AUTHORIZED" if valid else "CONTROLLER_COLLECT_UNAUTHORIZED", fail_closed=not valid)


def controller_request_replay_receipt(*, request_ids: Sequence[Any], accepted_request_ids: Sequence[Any]) -> dict[str, Any]:
    requests = list(request_ids)
    accepted = list(accepted_request_ids)
    valid = bool(requests) and len(requests) == len(set(requests)) and len(accepted) == len(set(accepted)) and set(accepted).issubset(requests)
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_REQUESTS_IDEMPOTENT" if valid else "CONTROLLER_REQUEST_REPLAYED", fail_closed=not valid)


def controller_epoch_receipt(*, observed_epoch: Any, current_epoch: Any) -> dict[str, Any]:
    valid = _controller_integer(observed_epoch) and _controller_integer(current_epoch) and observed_epoch == current_epoch
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_EPOCH_CURRENT" if valid else "CONTROLLER_EPOCH_STALE", fail_closed=not valid)


def controller_hash_receipt(*, expected_sha: Any, actual_sha: Any) -> dict[str, Any]:
    valid = _controller_sha(expected_sha) and _controller_sha(actual_sha) and expected_sha == actual_sha
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_SHA_MATCH" if valid else "CONTROLLER_SHA_MISMATCH", fail_closed=not valid)


def controller_lease_receipt(*, worker_id: Any, lease_owner: Any, lease_expires_at_ms: Any, now_ms: Any) -> dict[str, Any]:
    valid = isinstance(worker_id, str) and bool(worker_id.strip()) and worker_id == lease_owner and _controller_integer(lease_expires_at_ms) and _controller_integer(now_ms) and now_ms < lease_expires_at_ms
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_LEASE_ACTIVE" if valid else "CONTROLLER_LEASE_EXPIRED_OR_MISMATCHED", fail_closed=not valid)


def controller_single_owner_receipt(*, owner_ids: Sequence[Any]) -> dict[str, Any]:
    owners = list(owner_ids)
    valid = len(owners) == 1 and isinstance(owners[0], str) and bool(owners[0].strip())
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_SINGLE_OWNER" if valid else "CONTROLLER_SPLIT_BRAIN", fail_closed=not valid)


def controller_checkpoint_receipt(*, checkpoint: Mapping[str, Any], required_fields: Sequence[str]) -> dict[str, Any]:
    required = list(required_fields)
    valid = isinstance(checkpoint, Mapping) and bool(required) and all(isinstance(field, str) and checkpoint.get(field) not in (None, "") for field in required) and checkpoint.get("saved") is True
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_CHECKPOINT_COMPLETE" if valid else "CONTROLLER_CHECKPOINT_PARTIAL", fail_closed=not valid)


def controller_runner_receipt(*, runner_label: Any) -> dict[str, Any]:
    normalized = runner_label.strip().lower() if isinstance(runner_label, str) else ""
    valid = bool(normalized) and "self-hosted" not in normalized and "self_hosted" not in normalized and "localhost" not in normalized and normalized in {"ubuntu-latest", "windows-latest", "macos-latest", "github-hosted"}
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_GITHUB_HOSTED" if valid else "CONTROLLER_RUNNER_FORBIDDEN", fail_closed=not valid)


def controller_done_coverage_receipt(*, phase: Any, analysis_stage: Any, coverage_status: Any, required_proofs: Sequence[Any], completed_proofs: Sequence[Any]) -> dict[str, Any]:
    required = set(required_proofs)
    completed = set(completed_proofs)
    valid = phase == "ANALYZE" and analysis_stage == "DONE" and coverage_status == "PROVEN" and bool(required) and required.issubset(completed)
    return _controller_base("PROVEN" if valid else "REJECTED", verdict="CONTROLLER_DONE_COVERAGE_COMPLETE" if valid else "CONTROLLER_DONE_WITHOUT_COVERAGE", fail_closed=not valid)


__all__ = [
    "TransitionReceipt", "PhaseController", "controller_state_safety_receipt",
    "controller_required_field_receipt", "controller_null_field_receipt", "controller_field_type_receipt",
    "controller_finite_receipt", "controller_cutoff_receipt", "controller_age_receipt",
    "controller_duplicate_receipt", "controller_retry_receipt", "controller_replay_receipt",
    "controller_stage_order_receipt", "controller_collect_authorization_receipt",
    "controller_request_replay_receipt", "controller_epoch_receipt", "controller_hash_receipt",
    "controller_lease_receipt", "controller_single_owner_receipt", "controller_checkpoint_receipt",
    "controller_runner_receipt", "controller_done_coverage_receipt",
    "economic_freeze_to_controller_boundary_receipt", "controller_to_dispatch_boundary_receipt",
    "native_venue_to_controller_boundary_receipt",
]
