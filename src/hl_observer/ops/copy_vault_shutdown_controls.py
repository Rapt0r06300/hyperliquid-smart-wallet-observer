"""Fail-closed shutdown, recovery and writer-lifecycle controls for Copy-Vault."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$", re.IGNORECASE)


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _hash(value: Any) -> bool:
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


def session_harvest_open_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Make harvest-open failure blocking rather than silently continuing."""
    if not isinstance(state, Mapping) or not isinstance(state.get("harvest_opened"), bool) or not isinstance(state.get("error"), bool):
        return _base("UNMEASURABLE", reason="harvest_open_state_missing")
    valid = (state["harvest_opened"] and not state["error"]) or (state["error"] and state.get("blocking") is True)
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="HARVEST_OPEN_FAILURE_BLOCKS" if valid else "HARVEST_OPEN_FAILURE_IGNORED",
        harvest_opened=state["harvest_opened"],
        error=state["error"],
    )


def all_writers_stopped_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require an explicit stop proof for every writer before shutdown completes."""
    if not rows:
        return _base("MORE_DATA", reason="empty_writer_stop_proof")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not str(row.get("writer_id") or "").strip() or row.get("stopped") is not True or row.get("active") is not False
    ]
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="ALL_WRITERS_STOPPED" if not invalid else "WRITER_STILL_ACTIVE",
        writers=len(rows),
        invalid_rows=invalid,
    )


def idempotent_close_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reject duplicate close actions from Q and external stop signals."""
    if not rows:
        return _base("MORE_DATA", reason="empty_close_events")
    seen: set[str] = set()
    invalid: list[int] = []
    for index, row in enumerate(rows):
        close_id = str(row.get("position_id") or "") if isinstance(row, Mapping) else ""
        if not close_id or close_id in seen or row.get("idempotency_key") is None if isinstance(row, Mapping) else True:
            invalid.append(index)
        else:
            seen.add(close_id)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="CLOSE_ACTION_IDEMPOTENT" if not invalid else "DOUBLE_CLOSE_DETECTED",
        positions=len(rows),
        invalid_rows=invalid,
    )


def pre_force_stop_snapshot_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require a durable paper-state snapshot before forced stop escalation."""
    if not isinstance(state, Mapping) or state.get("snapshot_saved") is not True or not _hash(state.get("state_hash")) or state.get("before_force_stop") is not True:
        return _base("REJECTED", reason="pre_force_stop_snapshot_missing")
    return _base("PROVEN", verdict="STATE_SAVED_BEFORE_FORCE_STOP", state_hash=state["state_hash"])


def restore_paper_positions_receipt(
    before: Sequence[Mapping[str, Any]], after: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    """Restore paper positions only when identity and quantities reconcile."""
    if not before or not after:
        return _base("MORE_DATA", reason="empty_position_recovery")
    def normalized(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
        values: dict[str, Any] = {}
        for row in rows:
            if not isinstance(row, Mapping) or not str(row.get("position_id") or "").strip() or row.get("paper_read_only") is not True:
                return None
            values[str(row["position_id"])] = row.get("quantity")
        return values
    left, right = normalized(before), normalized(after)
    if left is None or right is None:
        return _base("UNMEASURABLE", reason="position_recovery_identity_missing")
    equal = left == right
    return _base(
        "PROVEN" if equal else "REJECTED",
        verdict="PAPER_POSITIONS_RESTORED" if equal else "PAPER_POSITION_RECOVERY_MISMATCH",
        position_count=len(left),
    )


def sqlite_commit_crash_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require atomic commit semantics when a process dies during SQLite commit."""
    if not isinstance(state, Mapping) or not isinstance(state.get("process_died"), bool) or state.get("commit_status") not in {"COMMITTED", "ROLLED_BACK"} or state.get("atomic") is not True:
        return _base("UNMEASURABLE", reason="sqlite_commit_recovery_incomplete")
    return _base("PROVEN", verdict="SQLITE_COMMIT_ATOMIC_ON_PROCESS_DEATH", commit_status=state["commit_status"])


def scoped_stop_file_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Prevent one run from deleting another run's stop file."""
    if not isinstance(state, Mapping) or not str(state.get("current_run_id") or "").strip() or not str(state.get("stop_file_run_id") or "").strip():
        return _base("UNMEASURABLE", reason="stop_file_scope_missing")
    same = state["current_run_id"] == state["stop_file_run_id"]
    return _base(
        "PROVEN" if same else "REJECTED",
        verdict="STOP_FILE_SCOPED_TO_RUN" if same else "STOP_FILE_FROM_OTHER_RUN",
        current_run_id=state["current_run_id"],
        stop_file_run_id=state["stop_file_run_id"],
    )


def poller_max_runs_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require a bounded max-runs loop to exit cleanly."""
    if not isinstance(state, Mapping) or not isinstance(state.get("runs"), int) or not isinstance(state.get("max_runs"), int) or state["runs"] < 0 or state["max_runs"] <= 0:
        return _base("UNMEASURABLE", reason="max_runs_contract_missing")
    valid = state["runs"] <= state["max_runs"] and state.get("clean_exit") is True
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="POLLER_MAX_RUNS_CLEAN_EXIT" if valid else "POLLER_MAX_RUNS_VIOLATED",
        runs=state["runs"],
        max_runs=state["max_runs"],
    )


def restart_log_preservation_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require logs to remain linked and preserved across restarts."""
    if not rows:
        return _base("MORE_DATA", reason="empty_restart_log_history")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not str(row.get("restart_id") or "").strip() or not str(row.get("log_ref") or "").strip() or row.get("preserved") is not True
    ]
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="LOGS_PRESERVED_ACROSS_RESTARTS" if not invalid else "LOG_PRESERVATION_FAILED",
        restarts=len(rows),
        invalid_rows=invalid,
    )


def shutdown_escalation_receipt(
    steps: Sequence[Mapping[str, Any]], *, deadline_ms: int
) -> dict[str, Any]:
    """Require bounded, ordered close/escalation steps."""
    if not steps or not isinstance(deadline_ms, int) or deadline_ms <= 0:
        return _base("MORE_DATA" if not steps else "UNMEASURABLE", reason="invalid_shutdown_deadline")
    invalid: list[int] = []
    previous = -1
    for index, step in enumerate(steps):
        elapsed = step.get("elapsed_ms") if isinstance(step, Mapping) else None
        if not isinstance(elapsed, int) or isinstance(elapsed, bool) or elapsed < previous or elapsed > deadline_ms or not str(step.get("stage") or "").strip() if isinstance(step, Mapping) else True:
            invalid.append(index)
        else:
            previous = elapsed
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="SHUTDOWN_ESCALATION_BOUNDED" if not invalid else "SHUTDOWN_ESCALATION_UNBOUNDED",
        deadline_ms=deadline_ms,
        invalid_rows=invalid,
    )


__all__ = [
    "session_harvest_open_receipt",
    "all_writers_stopped_receipt",
    "idempotent_close_receipt",
    "pre_force_stop_snapshot_receipt",
    "restore_paper_positions_receipt",
    "sqlite_commit_crash_receipt",
    "scoped_stop_file_receipt",
    "poller_max_runs_receipt",
    "restart_log_preservation_receipt",
    "shutdown_escalation_receipt",
]
