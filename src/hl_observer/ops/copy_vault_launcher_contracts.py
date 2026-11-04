"""Read-only launcher contracts for the remaining early LCH checks."""

from __future__ import annotations

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


def preflight_after_version_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require preflight to run again after a launcher version change."""
    if not rows:
        return _base("MORE_DATA", reason="empty_version_preflight")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("version_changed") is not False
        and row.get("preflight_rerun") is not True
        or row.get("preflight_status") not in {"PASS", "NO_GO"}
        or row.get("paper_read_only") is not True
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="VERSION_CHANGE_PREFLIGHT_REPLAYED", invalid_rows=invalid)


def status_code_propagation_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require launcher status code to equal the authoritative component code."""
    if not rows:
        return _base("MORE_DATA", reason="empty_status_code_propagation")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not isinstance(row.get("component_code"), int)
        or row.get("launcher_code") != row.get("component_code")
        or not str(row.get("component") or "").strip()
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="STATUS_CODE_PROPAGATED", invalid_rows=invalid)


def collector_code_propagation_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require collector failure/success codes to reach the launcher result."""
    if not rows:
        return _base("MORE_DATA", reason="empty_collector_code_propagation")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("source") != "COLLECTOR"
        or not isinstance(row.get("collector_code"), int)
        or row.get("launcher_code") != row.get("collector_code")
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="COLLECTOR_CODE_PROPAGATED", invalid_rows=invalid)


def maintenance_profile_code_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep maintenance-profile exit codes explicit and paper-only."""
    if not rows:
        return _base("MORE_DATA", reason="empty_maintenance_profile_code")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("profile") != "MAINTENANCE"
        or not isinstance(row.get("profile_code"), int)
        or row.get("launcher_code") != row.get("profile_code")
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="MAINTENANCE_PROFILE_CODE_PROPAGATED", invalid_rows=invalid)


def research_profile_code_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep research-profile exit codes explicit and non-authoritative."""
    if not rows:
        return _base("MORE_DATA", reason="empty_research_profile_code")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("profile") != "RESEARCH"
        or not isinstance(row.get("profile_code"), int)
        or row.get("launcher_code") != row.get("profile_code")
        or row.get("real_execution") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="RESEARCH_PROFILE_CODE_PROPAGATED", invalid_rows=invalid)


def daily_report_code_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require daily report commands to return their own explicit code."""
    if not rows:
        return _base("MORE_DATA", reason="empty_daily_report_code")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("command") != "DAILY_REPORT"
        or not isinstance(row.get("report_code"), int)
        or row.get("launcher_code") != row.get("report_code")
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="DAILY_REPORT_CODE_PROPAGATED", invalid_rows=invalid)


def self_test_code_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require self-test outcome to be the launcher outcome."""
    if not rows:
        return _base("MORE_DATA", reason="empty_self_test_code")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("command") != "SELF_TEST"
        or not isinstance(row.get("self_test_code"), int)
        or row.get("launcher_code") != row.get("self_test_code")
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="SELF_TEST_CODE_PROPAGATED", invalid_rows=invalid)


def reset_paper_code_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require reset-paper to be explicit and never a live reset."""
    if not rows:
        return _base("MORE_DATA", reason="empty_reset_paper_code")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("command") != "RESET_PAPER"
        or row.get("mode") != "PAPER"
        or row.get("real_execution") is not False
        or not isinstance(row.get("reset_code"), int)
        or row.get("launcher_code") != row.get("reset_code")
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="RESET_PAPER_CODE_PROPAGATED", invalid_rows=invalid)


def audit_code_result_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Expose AUDIT_CODE in the launcher result without hiding failure."""
    if not rows:
        return _base("MORE_DATA", reason="empty_audit_code_result")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not isinstance(row.get("audit_code"), int)
        or row.get("launcher_code") != row.get("audit_code")
        or row.get("audit_code_visible") is not True
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="AUDIT_CODE_EXPOSED", invalid_rows=invalid)


def audit_no_pip_install_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Ensure audit does not install dependencies automatically."""
    if not rows:
        return _base("MORE_DATA", reason="empty_audit_dependency_policy")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("audit_mode") != "READ_ONLY"
        or row.get("pip_install_attempted") is not False
        or row.get("dependency_change") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="AUDIT_NO_AUTOMATIC_PIP_INSTALL", invalid_rows=invalid)


def unknown_subcommand_error_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require unknown launcher commands to return a deterministic error."""
    if not rows:
        return _base("MORE_DATA", reason="empty_unknown_subcommand")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("command_known") is not False
        or not isinstance(row.get("error_code"), int)
        or row.get("error_code") == 0
        or row.get("execution_attempted") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="UNKNOWN_SUBCOMMAND_FAILS_DETERMINISTICALLY", invalid_rows=invalid)


def process_alive_source_ready_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep process liveness separate from source readiness."""
    if not rows:
        return _base("MORE_DATA", reason="empty_process_source_state")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not isinstance(row.get("process_alive"), bool)
        or not isinstance(row.get("source_ready"), bool)
        or (row.get("source_ready") is True and row.get("process_alive") is not True)
        or row.get("readiness_claim") != row.get("source_ready")
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="PROCESS_LIVENESS_SOURCE_READINESS_DISTINCT", invalid_rows=invalid)


def harvest_start_idempotence_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require repeated HARVEST starts to share one session and one writer."""
    if len(rows) < 2:
        return _base("MORE_DATA", reason="need_two_harvest_starts")
    session_ids = {row.get("session_id") for row in rows if isinstance(row, Mapping)}
    leaders = [row for row in rows if isinstance(row, Mapping) and row.get("result") == "STARTED"]
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("command") != "HARVEST"
        or not str(row.get("session_id") or "").strip()
        or row.get("result") not in {"STARTED", "IDEMPOTENT_NOOP"}
    ]
    if len(session_ids) != 1 or len(leaders) != 1:
        invalid.append("single_session_single_writer")
    return _base("PROVEN" if not invalid else "REJECTED", verdict="HARVEST_START_IDEMPOTENT", invalid_rows=invalid)


def native_venues_scope_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Keep native-venue requirements outside the active Copy-Vault launcher scope."""
    if not rows:
        return _base("MORE_DATA", reason="empty_native_venue_scope")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("family") != "Copy-Vault"
        or row.get("native_venues_required") is not False
        or row.get("scope_state") != "ACTIVE"
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="NATIVE_VENUES_REQUIREMENT_OUT_OF_SCOPE", invalid_rows=invalid)


def experimental_paper_shadow_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require explicit opt-in before an experimental paper shadow is started."""
    if not rows:
        return _base("MORE_DATA", reason="empty_experimental_shadow")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("mode") != "PAPER_SHADOW"
        or row.get("explicit_opt_in") is not True
        or row.get("real_execution") is not False
        or row.get("implicit_start") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="EXPERIMENTAL_PAPER_SHADOW_EXPLICIT", invalid_rows=invalid)


__all__ = [
    "preflight_after_version_receipt",
    "status_code_propagation_receipt",
    "collector_code_propagation_receipt",
    "maintenance_profile_code_receipt",
    "research_profile_code_receipt",
    "daily_report_code_receipt",
    "self_test_code_receipt",
    "reset_paper_code_receipt",
    "audit_code_result_receipt",
    "audit_no_pip_install_receipt",
    "unknown_subcommand_error_receipt",
    "process_alive_source_ready_receipt",
    "harvest_start_idempotence_receipt",
    "native_venues_scope_receipt",
    "experimental_paper_shadow_receipt",
]
