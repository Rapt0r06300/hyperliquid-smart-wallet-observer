from hl_observer.ops.copy_vault_hosted_controls import (
    concurrency_cancel_receipt,
    fork_trigger_receipt,
    github_token_permissions_receipt,
    hosted_rate_bound_receipt,
    hosted_runner_boundary_receipt,
    immutable_action_cache_receipt,
    publication_tag_collision_receipt,
    retry_publication_idempotency_receipt,
    schedule_saturation_receipt,
    upload_failure_exit_receipt,
)


def test_bug_261_schedule_is_preserved_under_saturation():
    assert schedule_saturation_receipt(scheduled=True, dispatch_preserved=True)["status"] == "PROVEN"
    assert schedule_saturation_receipt(scheduled=True, dispatch_preserved=False)["status"] == "REJECTED"


def test_bug_262_cancellation_saves_checkpoint():
    assert concurrency_cancel_receipt(collection_active=True, cancelled=True, checkpoint_saved=True)["status"] == "PROVEN"
    assert concurrency_cancel_receipt(collection_active=True, cancelled=True, checkpoint_saved=False)["status"] == "REJECTED"


def test_bug_263_publication_tag_is_unique():
    assert publication_tag_collision_receipt(tag="v1", campaign_ids=["c1", "c1"])["status"] == "PROVEN"
    assert publication_tag_collision_receipt(tag="v1", campaign_ids=["c1", "c2"])["status"] == "REJECTED"


def test_bug_264_github_token_is_read_only():
    assert github_token_permissions_receipt(permissions=["contents:read"])["status"] == "PROVEN"
    assert github_token_permissions_receipt(permissions=["contents:write"])["status"] == "REJECTED"


def test_bug_265_runner_is_github_hosted():
    assert hosted_runner_boundary_receipt(runner_kind="github-hosted", self_hosted=False, local_dependency=False)["status"] == "PROVEN"
    assert hosted_runner_boundary_receipt(runner_kind="self-hosted", self_hosted=True, local_dependency=True)["status"] == "REJECTED"


def test_bug_266_fork_trigger_is_not_exact_sha_proof():
    sha = "a" * 40
    assert fork_trigger_receipt(fork_event=False, trusted_ref=True, exact_sha=sha)["status"] == "PROVEN"
    assert fork_trigger_receipt(fork_event=True, trusted_ref=False, exact_sha=sha)["status"] == "REJECTED"


def test_bug_267_action_cache_is_immutable():
    assert immutable_action_cache_receipt(cache_key="k", immutable=True, includes_code_sha=True, mutable=False)["status"] == "PROVEN"
    assert immutable_action_cache_receipt(cache_key="k", immutable=False, includes_code_sha=True, mutable=True)["status"] == "REJECTED"


def test_bug_268_upload_failure_fails_job():
    assert upload_failure_exit_receipt(upload_failed=False, job_success=True)["status"] == "PROVEN"
    assert upload_failure_exit_receipt(upload_failed=True, job_success=True)["status"] == "REJECTED"


def test_bug_269_publication_retry_is_idempotent():
    assert retry_publication_idempotency_receipt(publication_ids=["p1", "p1"], tag="v1")["status"] == "PROVEN"
    assert retry_publication_idempotency_receipt(publication_ids=["p1", "p2"], tag="v1")["status"] == "REJECTED"


def test_bug_270_hosted_rate_is_bounded():
    assert hosted_rate_bound_receipt(request_count=5, rate_limit=5, throttled=False)["status"] == "PROVEN"
    assert hosted_rate_bound_receipt(request_count=6, rate_limit=5, throttled=False)["status"] == "REJECTED"
