from hl_observer.ops.copy_vault_shutdown_controls import (
    all_writers_stopped_receipt,
    idempotent_close_receipt,
    poller_max_runs_receipt,
    pre_force_stop_snapshot_receipt,
    restart_log_preservation_receipt,
    restore_paper_positions_receipt,
    scoped_stop_file_receipt,
    session_harvest_open_receipt,
    shutdown_escalation_receipt,
    sqlite_commit_crash_receipt,
)


def test_lch161_harvest_open_failure_is_blocking() -> None:
    assert session_harvest_open_receipt({"harvest_opened": False, "error": True, "blocking": True})["status"] == "PROVEN"
    assert session_harvest_open_receipt({"harvest_opened": False, "error": True, "blocking": False})["status"] == "REJECTED"


def test_lch162_requires_all_writers_stopped() -> None:
    assert all_writers_stopped_receipt([{"writer_id": "w1", "stopped": True, "active": False}])["status"] == "PROVEN"
    assert all_writers_stopped_receipt([{"writer_id": "w1", "stopped": False, "active": True}])["status"] == "REJECTED"


def test_lch163_rejects_duplicate_close() -> None:
    rows = [{"position_id": "p1", "idempotency_key": "k1"}]
    assert idempotent_close_receipt(rows)["status"] == "PROVEN"
    assert idempotent_close_receipt(rows + rows)["status"] == "REJECTED"


def test_lch164_requires_snapshot_before_force_stop() -> None:
    assert pre_force_stop_snapshot_receipt({"snapshot_saved": True, "state_hash": "a" * 64, "before_force_stop": True})["status"] == "PROVEN"
    assert pre_force_stop_snapshot_receipt({"snapshot_saved": False, "state_hash": "a" * 64, "before_force_stop": True})["status"] == "REJECTED"


def test_lch165_restores_paper_positions_by_identity() -> None:
    rows = [{"position_id": "p1", "quantity": 2, "paper_read_only": True}]
    assert restore_paper_positions_receipt(rows, list(rows))["status"] == "PROVEN"
    assert restore_paper_positions_receipt(rows, [{"position_id": "p1", "quantity": 3, "paper_read_only": True}])["status"] == "REJECTED"


def test_lch166_requires_atomic_sqlite_commit_recovery() -> None:
    assert sqlite_commit_crash_receipt({"process_died": True, "commit_status": "ROLLED_BACK", "atomic": True})["status"] == "PROVEN"
    assert sqlite_commit_crash_receipt({"process_died": True, "commit_status": "COMMITTED", "atomic": False})["status"] == "UNMEASURABLE"


def test_lch167_scopes_stop_file_to_current_run() -> None:
    assert scoped_stop_file_receipt({"current_run_id": "r1", "stop_file_run_id": "r1"})["status"] == "PROVEN"
    assert scoped_stop_file_receipt({"current_run_id": "r1", "stop_file_run_id": "r2"})["status"] == "REJECTED"


def test_lch168_requires_clean_max_runs_exit() -> None:
    assert poller_max_runs_receipt({"runs": 3, "max_runs": 3, "clean_exit": True})["status"] == "PROVEN"
    assert poller_max_runs_receipt({"runs": 4, "max_runs": 3, "clean_exit": True})["status"] == "REJECTED"


def test_lch169_preserves_logs_across_restarts() -> None:
    assert restart_log_preservation_receipt([{"restart_id": "r1", "log_ref": "log:1", "preserved": True}])["status"] == "PROVEN"
    assert restart_log_preservation_receipt([{"restart_id": "r1", "log_ref": "log:1", "preserved": False}])["status"] == "REJECTED"


def test_lch170_bounds_shutdown_escalation() -> None:
    rows = [{"stage": "graceful", "elapsed_ms": 10}, {"stage": "forced", "elapsed_ms": 20}]
    assert shutdown_escalation_receipt(rows, deadline_ms=30)["status"] == "PROVEN"
    rows[1]["elapsed_ms"] = 40
    assert shutdown_escalation_receipt(rows, deadline_ms=30)["status"] == "REJECTED"
