from hl_observer.ops.copy_vault_launcher_contracts import (
    audit_code_result_receipt,
    audit_no_pip_install_receipt,
    collector_code_propagation_receipt,
    daily_report_code_receipt,
    experimental_paper_shadow_receipt,
    harvest_start_idempotence_receipt,
    maintenance_profile_code_receipt,
    native_venues_scope_receipt,
    preflight_after_version_receipt,
    process_alive_source_ready_receipt,
    research_profile_code_receipt,
    reset_paper_code_receipt,
    self_test_code_receipt,
    status_code_propagation_receipt,
    unknown_subcommand_error_receipt,
)


def test_lch019_replays_preflight_after_version_change() -> None:
    row = {"version_changed": False, "preflight_rerun": True, "preflight_status": "PASS", "paper_read_only": True}
    assert preflight_after_version_receipt([row])["status"] == "PROVEN"
    row["version_changed"] = True
    row["preflight_rerun"] = False
    assert preflight_after_version_receipt([row])["status"] == "REJECTED"


def test_lch021_propagates_status_code() -> None:
    row = {"component": "launcher", "component_code": 0, "launcher_code": 0}
    assert status_code_propagation_receipt([row])["status"] == "PROVEN"


def test_lch022_propagates_collector_code() -> None:
    row = {"source": "COLLECTOR", "collector_code": 2, "launcher_code": 2}
    assert collector_code_propagation_receipt([row])["status"] == "PROVEN"


def test_lch023_propagates_maintenance_code() -> None:
    row = {"profile": "MAINTENANCE", "profile_code": 1, "launcher_code": 1}
    assert maintenance_profile_code_receipt([row])["status"] == "PROVEN"


def test_lch024_propagates_research_code() -> None:
    row = {"profile": "RESEARCH", "profile_code": 0, "launcher_code": 0, "real_execution": False}
    assert research_profile_code_receipt([row])["status"] == "PROVEN"


def test_lch025_propagates_daily_report_code() -> None:
    row = {"command": "DAILY_REPORT", "report_code": 0, "launcher_code": 0}
    assert daily_report_code_receipt([row])["status"] == "PROVEN"


def test_lch026_propagates_self_test_code() -> None:
    row = {"command": "SELF_TEST", "self_test_code": 0, "launcher_code": 0}
    assert self_test_code_receipt([row])["status"] == "PROVEN"


def test_lch027_propagates_reset_paper_code() -> None:
    row = {"command": "RESET_PAPER", "mode": "PAPER", "real_execution": False, "reset_code": 0, "launcher_code": 0}
    assert reset_paper_code_receipt([row])["status"] == "PROVEN"


def test_lch028_propagates_audit_code() -> None:
    row = {"audit_code": 3, "launcher_code": 3, "audit_code_visible": True}
    assert audit_code_result_receipt([row])["status"] == "PROVEN"


def test_lch029_audit_does_not_install_dependencies() -> None:
    row = {"audit_mode": "READ_ONLY", "pip_install_attempted": False, "dependency_change": False}
    assert audit_no_pip_install_receipt([row])["status"] == "PROVEN"


def test_lch030_unknown_command_is_error() -> None:
    row = {"command_known": False, "error_code": 2, "execution_attempted": False}
    assert unknown_subcommand_error_receipt([row])["status"] == "PROVEN"


def test_lch041_process_and_source_readiness_are_distinct() -> None:
    row = {"process_alive": True, "source_ready": False, "readiness_claim": False}
    assert process_alive_source_ready_receipt([row])["status"] == "PROVEN"


def test_lch042_harvest_start_is_idempotent() -> None:
    rows = [{"command": "HARVEST", "session_id": "s1", "result": "STARTED"}, {"command": "HARVEST", "session_id": "s1", "result": "IDEMPOTENT_NOOP"}]
    assert harvest_start_idempotence_receipt(rows)["status"] == "PROVEN"


def test_lch043_native_venues_requirement_is_out_of_scope() -> None:
    row = {"family": "Copy-Vault", "native_venues_required": False, "scope_state": "ACTIVE"}
    assert native_venues_scope_receipt([row])["status"] == "PROVEN"


def test_lch044_experimental_shadow_requires_opt_in() -> None:
    row = {"mode": "PAPER_SHADOW", "explicit_opt_in": True, "real_execution": False, "implicit_start": False}
    assert experimental_paper_shadow_receipt([row])["status"] == "PROVEN"
    row["implicit_start"] = True
    assert experimental_paper_shadow_receipt([row])["status"] == "REJECTED"
