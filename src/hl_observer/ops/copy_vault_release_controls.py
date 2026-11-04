"""Release and mission-closure controls for the Copy-Vault launcher."""

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


def golden_run_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require a complete, identified paper golden run from the launcher."""
    if not rows:
        return _base("MORE_DATA", reason="empty_golden_run")
    required = {"COLLECT", "ANALYZE", "REPLAY", "BACKTEST", "OOS", "FORWARD_PAPER"}
    observed = {row.get("phase") for row in rows if isinstance(row, Mapping)}
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("run_state") != "COMPLETED"
        or row.get("mode") != "PAPER"
        or not str(row.get("launcher_version") or "").strip()
        or not str(row.get("corpus_manifest_sha256") or "").strip()
        or row.get("real_execution") is not False
    ]
    if not required.issubset(observed):
        invalid.append("phase_coverage")
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="GOLDEN_PAPER_RUN_COMPLETE", invalid_rows=invalid)


def official_commands_no_user_pc_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require official commands to run on cloud runners, never on the user PC."""
    if not rows:
        return _base("MORE_DATA", reason="empty_official_command_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("command") or "").strip()
        or row.get("runner") != "github-hosted"
        or row.get("self_hosted") is not False
        or row.get("user_pc") is not False
        or row.get("ssh_or_tunnel") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="OFFICIAL_COMMANDS_CLOUD_ONLY", invalid_rows=invalid)


def portable_clone_no_history_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require portable clone checks to work without local history or user paths."""
    if not rows:
        return _base("MORE_DATA", reason="empty_portable_clone_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("clone_mode") != "PORTABLE"
        or row.get("history_present") is not False
        or row.get("startup_valid") is not True
        or row.get("absolute_user_path") is not False
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="PORTABLE_CLONE_WITHOUT_HISTORY", invalid_rows=invalid)


def cmd_refactor_parity_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require pre/post CMD refactor behavior parity for the same paper inputs."""
    if not rows:
        return _base("MORE_DATA", reason="empty_cmd_parity_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("input_manifest_sha256") is None
        or row.get("before_result") != row.get("after_result")
        or row.get("mode") != "PAPER"
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="CMD_REFACTOR_BEHAVIOR_PARITY", invalid_rows=invalid)


def launcher_rollback_plan_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require a bounded, non-destructive rollback plan for the canonical launcher."""
    if not rows:
        return _base("MORE_DATA", reason="empty_launcher_rollback_plan")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("current_version") or "").strip()
        or not str(row.get("previous_version") or "").strip()
        or not isinstance(row.get("steps"), list)
        or not row.get("steps")
        or row.get("destructive") is not False
        or row.get("force_push") is not False
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="LAUNCHER_ROLLBACK_PLAN_BOUNDED", invalid_rows=invalid)


def merge_real_trade_risk_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Block merge whenever a real-trade path risk is detected."""
    if not rows:
        return _base("MORE_DATA", reason="empty_trade_risk_merge_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("merge_allowed") is not (False if row.get("real_trade_risk") is True else True)
        or row.get("paper_read_only") is not True
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="MERGE_BLOCKS_REAL_TRADE_RISK", invalid_rows=invalid)


def merge_lock_targeted_stop_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require both lock testing and targeted stop testing before merge."""
    if not rows:
        return _base("MORE_DATA", reason="empty_lock_stop_merge_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("lock_test") is not True
        or row.get("targeted_stop_test") is not True
        or row.get("merge_allowed") is not True
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="MERGE_LOCK_AND_TARGETED_STOP_GREEN", invalid_rows=invalid)


def merge_pnl_config_divergence_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Block merge when PnL configuration hashes diverge."""
    if not rows:
        return _base("MORE_DATA", reason="empty_pnl_config_merge_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("main_config_sha256") or "").strip()
        or not str(row.get("candidate_config_sha256") or "").strip()
        or row.get("merge_allowed") is not (True if row.get("main_config_sha256") == row.get("candidate_config_sha256") else False)
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="MERGE_PNL_CONFIG_DIVERGENCE_GUARDED", invalid_rows=invalid)


def launcher_task_traceability_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Bind launcher task ids to roadmap indices and evidence references."""
    if not rows:
        return _base("MORE_DATA", reason="empty_launcher_traceability")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not isinstance(row.get("roadmap_index"), int)
        or row.get("roadmap_index") <= 0
        or not str(row.get("task_id") or "").strip()
        or not str(row.get("evidence_ref") or "").strip()
    ]
    return _base("PROVEN" if not invalid else "UNMEASURABLE", verdict="LAUNCHER_TASK_TRACEABLE", invalid_rows=invalid)


def launcher_mission_closure_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Close launcher work on verified safety/health contracts, not on profit."""
    if not rows:
        return _base("MORE_DATA", reason="empty_launcher_closure_inventory")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or row.get("profit_required") is not False
        or row.get("health_checks") is not True
        or row.get("safety_checks") is not True
        or row.get("scope_checks") is not True
        or row.get("paper_read_only") is not True
    ]
    return _base("PROVEN" if not invalid else "REJECTED", verdict="LAUNCHER_CLOSURE_INDEPENDENT_OF_PROFIT", invalid_rows=invalid)


__all__ = [
    "golden_run_receipt",
    "official_commands_no_user_pc_receipt",
    "portable_clone_no_history_receipt",
    "cmd_refactor_parity_receipt",
    "launcher_rollback_plan_receipt",
    "merge_real_trade_risk_receipt",
    "merge_lock_targeted_stop_receipt",
    "merge_pnl_config_divergence_receipt",
    "launcher_task_traceability_receipt",
    "launcher_mission_closure_receipt",
]
