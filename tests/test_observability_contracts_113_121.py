from hl_observer.ops.copy_vault_observability_controls import (
    certified_source_launcher_receipt,
    delayed_vs_dead_server_receipt,
    launcher_campaign_link_receipt,
    ledger_evolution_receipt,
    live_monitor_ui_health_receipt,
    queue_latency_attribution_receipt,
    startup_exception_receipt,
    ui_poller_health_receipt,
    version_code_sha_receipt,
)
from hl_observer.ops.copy_vault_launch_controls import source_module_status_receipt


def test_lch113_publishes_component_version_and_sha() -> None:
    row = {"component": "observer", "version": "1.0", "code_sha": "a" * 40}
    assert version_code_sha_receipt([row])["status"] == "PROVEN"
    row["code_sha"] = "bad"
    assert version_code_sha_receipt([row])["status"] == "UNMEASURABLE"


def test_lch114_attributes_network_and_cpu_queue_latency() -> None:
    assert queue_latency_attribution_receipt(
        [{"network_ms": 10, "cpu_queue_ms": 5, "total_ms": 15}]
    )["status"] == "PROVEN"
    assert queue_latency_attribution_receipt(
        [{"network_ms": 10, "cpu_queue_ms": 5, "total_ms": 20}]
    )["status"] == "UNMEASURABLE"


def test_lch115_monitor_does_not_mask_dead_ui() -> None:
    assert live_monitor_ui_health_receipt({"live": True}, {"live": True})["status"] == "PROVEN"
    assert live_monitor_ui_health_receipt({"live": True}, {"live": False})["status"] == "REJECTED"


def test_lch116_ui_does_not_mask_dead_poller() -> None:
    assert ui_poller_health_receipt({"live": True}, {"live": True})["status"] == "PROVEN"
    assert ui_poller_health_receipt({"live": True}, {"live": False})["status"] == "REJECTED"


def test_lch117_reports_init_and_warmup_exceptions() -> None:
    row = {"phase": "warmup", "exception_type": "TimeoutError", "message": "bounded", "handled": True}
    assert startup_exception_receipt([row])["status"] == "PROVEN"
    del row["message"]
    assert startup_exception_receipt([row])["status"] == "UNMEASURABLE"


def test_lch118_detects_ledger_without_evolution() -> None:
    assert ledger_evolution_receipt(
        [{"sequence": 1, "balance": 100}, {"sequence": 2, "balance": 101}]
    )["status"] == "PROVEN"
    assert ledger_evolution_receipt(
        [{"sequence": 1, "balance": 100}, {"sequence": 2, "balance": 100}]
    )["status"] == "REJECTED"


def test_lch119_distinguishes_delayed_data_from_dead_server() -> None:
    result = delayed_vs_dead_server_receipt(
        [{"server_heartbeat": True, "data_age_ms": 200, "expected_interval_ms": 100}]
    )
    assert result["status"] == "PROVEN"
    assert result["classifications"] == ["DELAYED_DATA"]


def test_lch120_links_launcher_logs_to_campaigns() -> None:
    row = {"log_path": "run.log", "campaign_id": "c1", "experiment_id": "e1", "run_id": "r1"}
    assert launcher_campaign_link_receipt([row])["status"] == "PROVEN"
    del row["run_id"]
    assert launcher_campaign_link_receipt([row])["status"] == "UNMEASURABLE"


def test_lch121_accepts_only_certified_paper_sources() -> None:
    row = {"certified": True, "manifest_hash": "a" * 64, "paper_read_only": True, "real_execution": False}
    assert certified_source_launcher_receipt([row])["status"] == "PROVEN"
    row["certified"] = False
    assert certified_source_launcher_receipt([row])["status"] == "REJECTED"


def test_lch112_source_module_status_is_explicit() -> None:
    assert source_module_status_receipt(
        [{"source": "l2", "module": "collector", "status": "ACTIVE"}]
    )["status"] == "PROVEN"
