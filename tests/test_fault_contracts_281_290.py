from hl_observer.ops.copy_vault_fault_injection_controls import (
    abrupt_parent_powershell_receipt,
    archive_replay_powerloss_receipt,
    bbo_loss_mids_live_receipt,
    concurrent_restart_receipt,
    l2_delta_discontinuity_receipt,
    network_loss_scan_receipt,
    pid_journal_disk_full_receipt,
    rest_429_budget_receipt,
    sqlite_corruption_receipt,
    stale_ws_without_tcp_close_receipt,
)


def test_lch281_network_loss_fails_closed() -> None:
    row = {"fault": "NETWORK_LOSS", "scan_state": "FAIL_CLOSED", "execution_attempted": False, "data_certified": False}
    assert network_loss_scan_receipt([row])["status"] == "PROVEN"
    row["execution_attempted"] = True
    assert network_loss_scan_receipt([row])["status"] == "REJECTED"


def test_lch282_429_retries_stay_within_budget() -> None:
    row = {"fault": "HTTP_429", "retries": 2, "max_retries": 3, "budget_units": 10, "consumed_units": 5, "fail_closed": True}
    assert rest_429_budget_receipt([row])["status"] == "PROVEN"
    row["consumed_units"] = 11
    assert rest_429_budget_receipt([row])["status"] == "REJECTED"


def test_lch283_stale_ws_is_handled_without_tcp_close() -> None:
    row = {"fault": "WS_STALE", "tcp_connected": True, "watchdog_state": "STALE_FAIL_CLOSED", "new_decisions": False}
    assert stale_ws_without_tcp_close_receipt([row])["status"] == "PROVEN"
    row["new_decisions"] = True
    assert stale_ws_without_tcp_close_receipt([row])["status"] == "REJECTED"


def test_lch284_bbo_loss_vetoes_with_mids_live() -> None:
    row = {"fault": "BBO_LOSS", "allmids_live": True, "bbo_available": False, "decision": "VETO_NO_BOOK"}
    assert bbo_loss_mids_live_receipt([row])["status"] == "PROVEN"
    row["decision"] = "ALLOW"
    assert bbo_loss_mids_live_receipt([row])["status"] == "REJECTED"


def test_lch285_l2_gap_is_quarantined() -> None:
    row = {"fault": "L2_DELTA_GAP", "expected_seq": 10, "received_seq": 12, "quarantined": True}
    assert l2_delta_discontinuity_receipt([row])["status"] == "PROVEN"
    row["quarantined"] = False
    assert l2_delta_discontinuity_receipt([row])["status"] == "REJECTED"


def test_lch286_sqlite_corruption_isolated() -> None:
    row = {"fault": "SQLITE_CORRUPTION", "integrity_check": "FAILED", "quarantined": True, "certified": False}
    assert sqlite_corruption_receipt([row])["status"] == "PROVEN"
    row["certified"] = True
    assert sqlite_corruption_receipt([row])["status"] == "REJECTED"


def test_lch287_disk_full_does_not_claim_liveness() -> None:
    row = {"fault": "DISK_FULL", "journal_append": False, "liveness_claim": False, "fail_closed": True}
    assert pid_journal_disk_full_receipt([row])["status"] == "PROVEN"
    row["liveness_claim"] = True
    assert pid_journal_disk_full_receipt([row])["status"] == "REJECTED"


def test_lch288_parent_stop_stops_writers() -> None:
    row = {"fault": "PARENT_POWERSHELL_STOP", "all_writers_stopped": True, "recovery_state": "PENDING", "certified": False}
    assert abrupt_parent_powershell_receipt([row])["status"] == "PROVEN"
    row["all_writers_stopped"] = False
    assert abrupt_parent_powershell_receipt([row])["status"] == "REJECTED"


def test_lch289_powerloss_replay_uses_checkpoint() -> None:
    row = {"fault": "POWER_LOSS", "checkpoint_id": "cp1", "manifest_sha256": "sha", "partial_certification": False, "resume_state": "CHECKPOINTED"}
    assert archive_replay_powerloss_receipt([row])["status"] == "PROVEN"
    row["partial_certification"] = True
    assert archive_replay_powerloss_receipt([row])["status"] == "UNMEASURABLE"


def test_lch290_concurrent_restart_has_one_lease_winner() -> None:
    rows = [{"fault": "CONCURRENT_RESTART", "lease_result": "WON", "started": True}, {"fault": "CONCURRENT_RESTART", "lease_result": "REFUSED", "started": False}]
    assert concurrent_restart_receipt(rows)["status"] == "PROVEN"
    rows[1]["started"] = True
    assert concurrent_restart_receipt(rows)["status"] == "REJECTED"
