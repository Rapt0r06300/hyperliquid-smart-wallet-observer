from hl_observer.ops.copy_vault_hosted_controls import (
    cloud_campaign_readonly_receipt,
    cloud_head_local_binary_receipt,
    collect_phase_epoch_receipt,
    git_sync_local_data_receipt,
    host_receipt_diagnostics_receipt,
    hosted_resume_outage_link_receipt,
    interface_loss_receipt,
    pc_runner_involuntary_receipt,
    receipt_cache_epoch_guard_receipt,
    shard_publication_lag_receipt,
)


def test_lch131_phase_epoch_is_control_plane_owned() -> None:
    state = {"phase": "COLLECT", "phase_epoch": 3, "epoch_source": "control_plane", "derived_from_pc": False}
    assert collect_phase_epoch_receipt(state)["status"] == "PROVEN"
    state["derived_from_pc"] = True
    assert collect_phase_epoch_receipt(state)["status"] == "REJECTED"


def test_lch132_cloud_campaign_status_is_read_only() -> None:
    assert cloud_campaign_readonly_receipt([{"campaign_id": "c1", "write_enabled": False, "paper_read_only": True}])["status"] == "PROVEN"
    assert cloud_campaign_readonly_receipt([{"campaign_id": "c1", "write_enabled": True, "paper_read_only": True}])["status"] == "REJECTED"


def test_lch133_host_receipts_link_diagnostics() -> None:
    row = {"receipt_id": "r1", "diagnostic_ref": "d1", "run_id": "run1", "artifact_sha": "a" * 64}
    assert host_receipt_diagnostics_receipt([row])["status"] == "PROVEN"
    del row["diagnostic_ref"]
    assert host_receipt_diagnostics_receipt([row])["status"] == "UNMEASURABLE"


def test_lch134_exposes_cloud_head_and_local_binary_separately() -> None:
    result = cloud_head_local_binary_receipt({"cloud_head_sha": "a" * 40, "local_binary_sha": "b" * 40})
    assert result["status"] == "PROVEN"
    assert result["same_identity"] is False


def test_lch135_rejects_pc_as_involuntary_runner() -> None:
    state = {"runner_kind": "github-hosted", "pc_runner": False, "self_hosted": False, "paper_read_only": True}
    assert pc_runner_involuntary_receipt(state)["status"] == "PROVEN"
    state["pc_runner"] = True
    assert pc_runner_involuntary_receipt(state)["status"] == "REJECTED"


def test_lch136_proves_git_sync_preserved_safe_manifest() -> None:
    before = {"safe_manifest_sha": "a" * 64, "safe_bytes": 100}
    after = dict(before)
    assert git_sync_local_data_receipt(before, after)["status"] == "PROVEN"
    after["safe_bytes"] = 101
    assert git_sync_local_data_receipt(before, after)["status"] == "REJECTED"


def test_lch137_measures_safe_shard_publication_lag() -> None:
    assert shard_publication_lag_receipt([{"created_ts_ms": 10, "published_ts_ms": 20}])["status"] == "PROVEN"
    assert shard_publication_lag_receipt([{"created_ts_ms": 20, "published_ts_ms": 10}])["status"] == "UNMEASURABLE"


def test_lch138_links_hosted_resume_to_local_outage() -> None:
    row = {"hosted_run_id": "run1", "resume_receipt_id": "r1", "local_outage_ref": "outage:1"}
    assert hosted_resume_outage_link_receipt([row])["status"] == "PROVEN"
    del row["local_outage_ref"]
    assert hosted_resume_outage_link_receipt([row])["status"] == "UNMEASURABLE"


def test_lch139_guards_receipt_cache_with_epoch() -> None:
    assert receipt_cache_epoch_guard_receipt([{"receipt_id": "r1", "phase_epoch": 1}, {"receipt_id": "r1", "phase_epoch": 1}])["status"] == "PROVEN"
    assert receipt_cache_epoch_guard_receipt([{"receipt_id": "r1", "phase_epoch": 1}, {"receipt_id": "r1", "phase_epoch": 2}])["status"] == "REJECTED"


def test_lch140_interface_loss_fails_closed() -> None:
    row = {"event": "network_lost", "fail_closed": True, "real_execution": False}
    assert interface_loss_receipt([row])["status"] == "PROVEN"
    row["fail_closed"] = False
    assert interface_loss_receipt([row])["status"] == "REJECTED"
