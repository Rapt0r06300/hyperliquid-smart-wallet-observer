"""Fail-closed Windows and CI controls for the Copy-Vault launcher."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


UNSAFE_CMD = re.compile(r"(?:\b(?:reset|clean|force[- ]?push|del|erase|format)\b)", re.IGNORECASE)


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def cmd_syntax_static_receipt(lines: Sequence[str]) -> dict[str, Any]:
    """Statically reject destructive command verbs without executing the script."""
    if not lines:
        return _base("MORE_DATA", reason="empty_cmd_script")
    invalid = [index for index, line in enumerate(lines) if not isinstance(line, str) or UNSAFE_CMD.search(line)]
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="CMD_STATIC_SYNTAX_SAFE" if not invalid else "CMD_DESTRUCTIVE_VERB_PRESENT",
        lines=len(lines),
        invalid_rows=invalid,
    )


def windows_lock_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require a lock owned by the current run before a Windows operation."""
    if not isinstance(state, Mapping) or not str(state.get("current_run_id") or "").strip() or not str(state.get("lock_owner") or "").strip() or not isinstance(state.get("acquired"), bool):
        return _base("UNMEASURABLE", reason="windows_lock_state_missing")
    valid = state["acquired"] is True and state["lock_owner"] == state["current_run_id"] and state.get("exclusive") is True
    return _base("PROVEN" if valid else "REJECTED", verdict="WINDOWS_LOCK_EXCLUSIVE" if valid else "WINDOWS_LOCK_INVALID")


def ci_late_preflight_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require a late CI preflight failure to stop before publishing artifacts."""
    if not isinstance(state, Mapping) or not isinstance(state.get("preflight_failed"), bool) or not isinstance(state.get("fail_closed"), bool):
        return _base("UNMEASURABLE", reason="late_preflight_state_missing")
    valid = state["preflight_failed"] and state["fail_closed"] and state.get("artifact_published") is False
    return _base("PROVEN" if valid else "REJECTED", verdict="CI_LATE_PREFLIGHT_FAIL_CLOSED" if valid else "CI_LATE_PREFLIGHT_LEAK", artifact_published=state.get("artifact_published"))


def errorlevel_propagation_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require each command result to carry its ERRORLEVEL into the final result."""
    if not rows:
        return _base("MORE_DATA", reason="empty_command_results")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not str(row.get("command") or "").strip() or not isinstance(row.get("exit_code"), int) or not isinstance(row.get("handled"), bool)
    ]
    nonzero_unhandled = [index for index, row in enumerate(rows) if isinstance(row, Mapping) and isinstance(row.get("exit_code"), int) and row.get("exit_code") != 0 and row.get("handled") is not True]
    invalid.extend(nonzero_unhandled)
    return _base("PROVEN" if not invalid else "REJECTED", verdict="ERRORLEVEL_PROPAGATED" if not invalid else "ERRORLEVEL_DROPPED", invalid_rows=sorted(set(invalid)))


def foreign_process_refusal_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Reject termination of a process that does not belong to the current run."""
    if not isinstance(state, Mapping) or not isinstance(state.get("process_owned_by_run"), bool) or not isinstance(state.get("termination_refused"), bool):
        return _base("UNMEASURABLE", reason="foreign_process_state_missing")
    valid = state["process_owned_by_run"] is False and state["termination_refused"] is True
    return _base("PROVEN" if valid else "REJECTED", verdict="FOREIGN_PROCESS_TERMINATION_REFUSED" if valid else "FOREIGN_PROCESS_TERMINATION_ALLOWED")


def foreign_port_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Refuse startup when a requested port is occupied by a foreign owner."""
    if not isinstance(state, Mapping) or not isinstance(state.get("port_occupied"), bool) or not isinstance(state.get("port_owned_by_run"), bool):
        return _base("UNMEASURABLE", reason="foreign_port_state_missing")
    valid = not state["port_occupied"] or state["port_owned_by_run"] or state.get("start_refused") is True
    return _base("PROVEN" if valid else "REJECTED", verdict="FOREIGN_PORT_START_REFUSED" if valid else "FOREIGN_PORT_START_ALLOWED")


def orphan_restart_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Require orphan process detection before a restart and forbid blind reuse."""
    if not isinstance(state, Mapping) or not isinstance(state.get("orphan_detected"), bool) or not isinstance(state.get("restart_planned"), bool):
        return _base("UNMEASURABLE", reason="orphan_restart_state_missing")
    valid = not state["orphan_detected"] or (state["restart_planned"] and state.get("orphan_reconciled") is True)
    return _base("PROVEN" if valid else "REJECTED", verdict="ORPHAN_RESTART_RECONCILED" if valid else "ORPHAN_RESTART_UNSAFE")


def copyvault_health_empty_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Classify empty Copy-Vault data as no-data/no-trade, never as healthy alpha."""
    if not isinstance(state, Mapping) or not isinstance(state.get("data_count"), int) or state["data_count"] < 0:
        return _base("UNMEASURABLE", reason="empty_health_state_missing")
    valid = state["data_count"] > 0 or (state["data_count"] == 0 and state.get("decision") in {"NO_DATA", "NO_TRADE"})
    return _base("PROVEN" if valid else "REJECTED", verdict="EMPTY_COPYVAULT_FAIL_CLOSED" if valid else "EMPTY_COPYVAULT_MISLABELED")


def cmd_ps_config_conflict_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Reject contradictory CMD and PowerShell runtime configuration."""
    if not isinstance(state, Mapping) or not isinstance(state.get("conflict_detected"), bool):
        return _base("UNMEASURABLE", reason="config_conflict_state_missing")
    valid = state["conflict_detected"] is False and state.get("effective_config_pinned") is True
    return _base("PROVEN" if valid else "REJECTED", verdict="CMD_PS_CONFIG_COHERENT" if valid else "CMD_PS_CONFIG_CONFLICT")


def runtime_tree_no_real_execution_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require every child in the runtime tree to remain paper-only."""
    if not rows:
        return _base("MORE_DATA", reason="empty_runtime_tree")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping) or not str(row.get("node") or "").strip() or row.get("real_execution") is not False or row.get("paper_read_only") is not True
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="RUNTIME_TREE_NO_REAL_EXECUTION" if not invalid else "RUNTIME_TREE_EXECUTION_PATH", invalid_rows=invalid)


__all__ = [
    "cmd_syntax_static_receipt",
    "windows_lock_receipt",
    "ci_late_preflight_receipt",
    "errorlevel_propagation_receipt",
    "foreign_process_refusal_receipt",
    "foreign_port_receipt",
    "orphan_restart_receipt",
    "copyvault_health_empty_receipt",
    "cmd_ps_config_conflict_receipt",
    "runtime_tree_no_real_execution_receipt",
]
