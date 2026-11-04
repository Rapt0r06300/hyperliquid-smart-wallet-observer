from hl_observer.ops.copy_vault_windows_controls import (
    ci_late_preflight_receipt,
    cmd_ps_config_conflict_receipt,
    cmd_syntax_static_receipt,
    copyvault_health_empty_receipt,
    errorlevel_propagation_receipt,
    foreign_port_receipt,
    foreign_process_refusal_receipt,
    orphan_restart_receipt,
    runtime_tree_no_real_execution_receipt,
    windows_lock_receipt,
)


def test_lch191_cmd_static_syntax_rejects_destructive_verbs() -> None:
    assert cmd_syntax_static_receipt(["set MODE=paper", "python -m audit"])["status"] == "PROVEN"
    assert cmd_syntax_static_receipt(["git reset --hard"])["status"] == "REJECTED"


def test_lch192_windows_lock_is_exclusive_and_owned() -> None:
    state = {"current_run_id": "r1", "lock_owner": "r1", "acquired": True, "exclusive": True}
    assert windows_lock_receipt(state)["status"] == "PROVEN"
    state["lock_owner"] = "r2"
    assert windows_lock_receipt(state)["status"] == "REJECTED"


def test_lch193_late_preflight_failure_is_fail_closed() -> None:
    state = {"preflight_failed": True, "fail_closed": True, "artifact_published": False}
    assert ci_late_preflight_receipt(state)["status"] == "PROVEN"
    state["artifact_published"] = True
    assert ci_late_preflight_receipt(state)["status"] == "REJECTED"


def test_lch194_errorlevel_is_handled() -> None:
    assert errorlevel_propagation_receipt([{"command": "audit", "exit_code": 0, "handled": True}])["status"] == "PROVEN"
    assert errorlevel_propagation_receipt([{"command": "audit", "exit_code": 1, "handled": False}])["status"] == "REJECTED"


def test_lch195_foreign_process_termination_is_refused() -> None:
    assert foreign_process_refusal_receipt({"process_owned_by_run": False, "termination_refused": True})["status"] == "PROVEN"
    assert foreign_process_refusal_receipt({"process_owned_by_run": False, "termination_refused": False})["status"] == "REJECTED"


def test_lch196_foreign_port_start_is_refused() -> None:
    assert foreign_port_receipt({"port_occupied": True, "port_owned_by_run": False, "start_refused": True})["status"] == "PROVEN"
    assert foreign_port_receipt({"port_occupied": True, "port_owned_by_run": False, "start_refused": False})["status"] == "REJECTED"


def test_lch197_orphan_restart_requires_reconciliation() -> None:
    assert orphan_restart_receipt({"orphan_detected": True, "restart_planned": True, "orphan_reconciled": True})["status"] == "PROVEN"
    assert orphan_restart_receipt({"orphan_detected": True, "restart_planned": True, "orphan_reconciled": False})["status"] == "REJECTED"


def test_lch198_empty_copyvault_is_no_data_or_no_trade() -> None:
    assert copyvault_health_empty_receipt({"data_count": 0, "decision": "NO_DATA"})["status"] == "PROVEN"
    assert copyvault_health_empty_receipt({"data_count": 0, "decision": "HEALTHY"})["status"] == "REJECTED"


def test_lch199_cmd_and_powershell_config_must_be_coherent() -> None:
    assert cmd_ps_config_conflict_receipt({"conflict_detected": False, "effective_config_pinned": True})["status"] == "PROVEN"
    assert cmd_ps_config_conflict_receipt({"conflict_detected": True, "effective_config_pinned": False})["status"] == "REJECTED"


def test_lch200_runtime_tree_remains_paper_only() -> None:
    row = {"node": "child", "real_execution": False, "paper_read_only": True}
    assert runtime_tree_no_real_execution_receipt([row])["status"] == "PROVEN"
    row["real_execution"] = True
    assert runtime_tree_no_real_execution_receipt([row])["status"] == "REJECTED"
