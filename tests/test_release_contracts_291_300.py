from hl_observer.ops.copy_vault_release_controls import (
    cmd_refactor_parity_receipt,
    golden_run_receipt,
    launcher_mission_closure_receipt,
    launcher_rollback_plan_receipt,
    launcher_task_traceability_receipt,
    merge_lock_targeted_stop_receipt,
    merge_pnl_config_divergence_receipt,
    merge_real_trade_risk_receipt,
    official_commands_no_user_pc_receipt,
    portable_clone_no_history_receipt,
)


def test_lch291_golden_run_has_all_paper_phases() -> None:
    phases = ["COLLECT", "ANALYZE", "REPLAY", "BACKTEST", "OOS", "FORWARD_PAPER"]
    rows = [{"phase": phase, "run_state": "COMPLETED", "mode": "PAPER", "launcher_version": "v1", "corpus_manifest_sha256": "m", "real_execution": False} for phase in phases]
    assert golden_run_receipt(rows)["status"] == "PROVEN"
    rows[0]["real_execution"] = True
    assert golden_run_receipt(rows)["status"] == "UNMEASURABLE"


def test_lch292_official_commands_are_cloud_only() -> None:
    row = {"command": "pytest", "runner": "github-hosted", "self_hosted": False, "user_pc": False, "ssh_or_tunnel": False}
    assert official_commands_no_user_pc_receipt([row])["status"] == "PROVEN"
    row["user_pc"] = True
    assert official_commands_no_user_pc_receipt([row])["status"] == "REJECTED"


def test_lch293_portable_clone_has_no_history_dependency() -> None:
    row = {"clone_mode": "PORTABLE", "history_present": False, "startup_valid": True, "absolute_user_path": False}
    assert portable_clone_no_history_receipt([row])["status"] == "PROVEN"
    row["history_present"] = True
    assert portable_clone_no_history_receipt([row])["status"] == "REJECTED"


def test_lch294_cmd_refactor_preserves_paper_behavior() -> None:
    row = {"input_manifest_sha256": "m", "before_result": "NO_GO", "after_result": "NO_GO", "mode": "PAPER"}
    assert cmd_refactor_parity_receipt([row])["status"] == "PROVEN"
    row["after_result"] = "GO"
    assert cmd_refactor_parity_receipt([row])["status"] == "REJECTED"


def test_lch295_rollback_plan_is_bounded() -> None:
    row = {"current_version": "v2", "previous_version": "v1", "steps": ["restore_manifest"], "destructive": False, "force_push": False}
    assert launcher_rollback_plan_receipt([row])["status"] == "PROVEN"
    row["force_push"] = True
    assert launcher_rollback_plan_receipt([row])["status"] == "UNMEASURABLE"


def test_lch296_merge_blocks_real_trade_risk() -> None:
    assert merge_real_trade_risk_receipt([{"real_trade_risk": True, "merge_allowed": False, "paper_read_only": True}])["status"] == "PROVEN"
    assert merge_real_trade_risk_receipt([{"real_trade_risk": True, "merge_allowed": True, "paper_read_only": True}])["status"] == "REJECTED"


def test_lch297_merge_requires_lock_and_targeted_stop() -> None:
    row = {"lock_test": True, "targeted_stop_test": True, "merge_allowed": True}
    assert merge_lock_targeted_stop_receipt([row])["status"] == "PROVEN"
    row["lock_test"] = False
    assert merge_lock_targeted_stop_receipt([row])["status"] == "REJECTED"


def test_lch298_merge_blocks_pnl_config_divergence() -> None:
    row = {"main_config_sha256": "same", "candidate_config_sha256": "same", "merge_allowed": True}
    assert merge_pnl_config_divergence_receipt([row])["status"] == "PROVEN"
    row["candidate_config_sha256"] = "other"
    row["merge_allowed"] = False
    assert merge_pnl_config_divergence_receipt([row])["status"] == "PROVEN"
    row["merge_allowed"] = True
    assert merge_pnl_config_divergence_receipt([row])["status"] == "REJECTED"


def test_lch299_launcher_tasks_are_traceable() -> None:
    row = {"roadmap_index": 722, "task_id": "LCH-300", "evidence_ref": "receipt:1"}
    assert launcher_task_traceability_receipt([row])["status"] == "PROVEN"
    assert launcher_task_traceability_receipt([{"roadmap_index": 722}])["status"] == "UNMEASURABLE"


def test_lch300_closure_does_not_depend_on_profit() -> None:
    row = {"profit_required": False, "health_checks": True, "safety_checks": True, "scope_checks": True, "paper_read_only": True}
    assert launcher_mission_closure_receipt([row])["status"] == "PROVEN"
    row["profit_required"] = True
    assert launcher_mission_closure_receipt([row])["status"] == "REJECTED"
