from hl_observer.ops.copy_vault_hosted_controls import (
    action_pin_receipt,
    actions_pagination_receipt,
    artifact_retention_receipt,
    catalog_commit_loop_receipt,
    concurrent_queue_alert_receipt,
    journal_flush_receipt,
    log_secret_redaction_receipt,
    release_transient_receipt,
    scheduled_branch_receipt,
    segment_timeout_boundary_receipt,
)


SHA_A = "a" * 40
SHA_B = "b" * 40


def test_bug_271_catalog_loop_is_bounded():
    assert catalog_commit_loop_receipt(catalog_sha=SHA_A, commit_sha=SHA_B, loop_count=1, max_loops=3)["status"] == "PROVEN"


def test_bug_272_journal_flush_requires_contiguous_records():
    assert journal_flush_receipt(records=[{"sequence": 0}, {"sequence": 1}], flushed_sequence=1)["status"] == "PROVEN"


def test_bug_273_timeout_requires_checkpoint_boundary():
    assert segment_timeout_boundary_receipt(completed=False, checkpoint_saved=True, partial_manifest=True, cutoff_preserved=True)["status"] == "PROVEN"


def test_bug_274_logs_are_redacted():
    assert log_secret_redaction_receipt(messages=["token=[REDACTED]"], forbidden_fragments=["secret-value"])["status"] == "PROVEN"


def test_bug_275_actions_pagination_is_complete():
    assert actions_pagination_receipt(pages=[{"page": 0, "count": 2}, {"page": 1, "count": 1}], total_count=3)["status"] == "PROVEN"


def test_bug_276_transient_release_is_retried():
    assert release_transient_receipt(status="timeout", retry_required=True, definitive_not_found=False)["status"] == "PROVEN"


def test_bug_277_queue_overflow_is_alerted():
    assert concurrent_queue_alert_receipt(queue_depth=11, capacity=10, alert_emitted=True)["status"] == "PROVEN"


def test_bug_278_scheduled_branch_is_bounded():
    assert scheduled_branch_receipt(workflow_ref="main", scheduled_ref="main", default_branch="main")["status"] == "PROVEN"


def test_bug_279_actions_are_sha_pinned():
    assert action_pin_receipt(actions=[f"actions/checkout@{SHA_A}"])["status"] == "PROVEN"


def test_bug_280_release_retention_is_durable():
    assert artifact_retention_receipt(artifact_retention_days=7, release_retention_days=90, released=True, release_asset_present=True)["status"] == "PROVEN"
