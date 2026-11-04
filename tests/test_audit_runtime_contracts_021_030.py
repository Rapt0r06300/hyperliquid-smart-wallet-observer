from __future__ import annotations

from pathlib import Path

from hl_observer.audit.copy_vault_runtime_audit_controls import (
    capability_health_receipt,
    controller_cadence_receipt,
    dispatch_fallback_verdict,
    event_structural_receipt,
    fee_revalidation_receipt,
    fills_pagination_receipt,
    receipt_gate,
    self_hosted_disabled_receipt,
    worker_failure_verdict,
    workflow_permissions_receipt,
)


ROOT = Path(__file__).resolve().parents[1]


def test_worker_failure_cannot_become_complete():
    assert worker_failure_verdict({"status": "COMPLETE"}, durable_ok=False) == "FAIL_CLOSED"
    assert worker_failure_verdict({"status": "FAILED"}, durable_ok=True) == "FAIL_CLOSED"


def test_receipt_requires_unit_receipt_and_checkpoint():
    assert receipt_gate(unit_ok=True, receipt_written=True, checkpoint_written=True) == "PROVEN"
    assert receipt_gate(unit_ok=True, receipt_written=False, checkpoint_written=True) == "UNKNOWN"


def test_transient_dispatch_is_deferred_not_success():
    assert dispatch_fallback_verdict(http_status=429, attempts=6) == "DEFERRED_RETRY"
    assert dispatch_fallback_verdict(http_status=200, attempts=1) == "DISPATCHED"
    assert dispatch_fallback_verdict(http_status=400, attempts=1) == "FAILED"


def test_diagnostic_permissions_are_read_only():
    assert workflow_permissions_receipt(contents="read")["status"] == "SAFE"
    assert workflow_permissions_receipt(contents="write")["status"] == "UNSAFE"


def test_self_hosted_workflow_is_explicitly_disabled():
    text = (ROOT / ".github/workflows/alina-self-hosted.yml").read_text(encoding="utf-8")
    assert self_hosted_disabled_receipt(text)["status"] == "DISABLED"


def test_controller_cadence_never_accepts_sub_five_minute_watchdog():
    assert controller_cadence_receipt(interval_minutes=5, empty_run_cost_known=True) == "PROVEN"
    assert controller_cadence_receipt(interval_minutes=1, empty_run_cost_known=True) == "UNKNOWN"
    assert controller_cadence_receipt(interval_minutes=5, empty_run_cost_known=False) == "MORE_DATA"


def test_file_presence_is_not_source_health():
    assert capability_health_receipt({"runtime_status": "HEALTHY", "status": "FILE_PRESENT", "replay_compatible": True}) == "UNKNOWN"
    assert capability_health_receipt({"runtime_status": "HEALTHY", "status": "ACTIVE", "replay_compatible": True}) == "PROVEN"


def test_structural_event_lineage_requires_ablation():
    assert event_structural_receipt(source="s", feature="f", consumer="c", ablation="a") == "PROVEN"
    assert event_structural_receipt(source="s", feature="f", consumer="c", ablation=None) == "STRUCTURAL_ONLY"


def test_fee_schedule_requires_hash_asof_and_source():
    assert fee_revalidation_receipt(schedule_sha256="a" * 64, as_of="2026-11-04", source="safe://fees") == "PROVEN"
    assert fee_revalidation_receipt(schedule_sha256=None, as_of="2026-11-04", source="safe://fees") == "UNKNOWN"


def test_fills_pagination_is_bounded_and_deduplicated():
    assert fills_pagination_receipt(page_size=2000, max_pages=5, max_fills=10000, dedup_by_identity=True) == "PROVEN"
    assert fills_pagination_receipt(page_size=2000, max_pages=0, max_fills=10000, dedup_by_identity=True) == "UNKNOWN"
