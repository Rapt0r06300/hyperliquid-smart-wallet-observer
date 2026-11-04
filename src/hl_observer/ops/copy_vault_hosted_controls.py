"""Fail-closed cloud, hosted-receipt and local-boundary controls for Copy-Vault."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$", re.IGNORECASE)


def _base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _sha(value: Any) -> bool:
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


def _int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def collect_phase_epoch_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Bind the COLLECT phase to a control-plane epoch, never to PC state."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="invalid_phase_state")
    epoch = state.get("phase_epoch")
    valid = state.get("phase") == "COLLECT" and _int(epoch) and epoch > 0 and state.get("epoch_source") == "control_plane" and state.get("derived_from_pc") is False
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="COLLECT_PHASE_EPOCH_EXPLICIT" if valid else "COLLECT_PHASE_EPOCH_PC_DERIVED",
        phase=state.get("phase"),
        phase_epoch=epoch,
        epoch_source=state.get("epoch_source"),
    )


def cloud_campaign_readonly_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require campaign cloud status to be observational and read-only."""
    if not rows:
        return _base("MORE_DATA", reason="empty_cloud_campaign_status")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("campaign_id") or "").strip()
        or not isinstance(row.get("write_enabled"), bool)
        or row.get("write_enabled") is not False
        or row.get("paper_read_only") is not True
    ]
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="CLOUD_CAMPAIGN_STATUS_READ_ONLY" if not invalid else "CLOUD_CAMPAIGN_WRITE_PATH_PRESENT",
        campaigns=len(rows),
        invalid_rows=invalid,
    )


def host_receipt_diagnostics_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Link each hosted Copy-Vault receipt to an actionable diagnostic and artifact."""
    if not rows:
        return _base("MORE_DATA", reason="empty_host_receipts")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("receipt_id") or "").strip()
        or not str(row.get("diagnostic_ref") or "").strip()
        or not str(row.get("run_id") or "").strip()
        or not _sha(row.get("artifact_sha"))
    ]
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="HOST_RECEIPT_LINKED_TO_DIAGNOSTIC" if not invalid else "HOST_RECEIPT_DIAGNOSTIC_LINK_MISSING",
        receipts=len(rows),
        invalid_rows=invalid,
    )


def cloud_head_local_binary_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Expose cloud HEAD and local binary identity as separate fields."""
    if not isinstance(state, Mapping) or not _sha(state.get("cloud_head_sha")) or not _sha(state.get("local_binary_sha")):
        return _base("UNMEASURABLE", reason="cloud_or_local_identity_missing")
    return _base(
        "PROVEN",
        verdict="CLOUD_HEAD_DISTINCT_FROM_LOCAL_BINARY_IDENTITY",
        cloud_head_sha=state["cloud_head_sha"],
        local_binary_sha=state["local_binary_sha"],
        same_identity=state["cloud_head_sha"].lower() == state["local_binary_sha"].lower(),
    )


def pc_runner_involuntary_receipt(state: Mapping[str, Any]) -> dict[str, Any]:
    """Reject an execution contract that could turn the operator PC into a runner."""
    if not isinstance(state, Mapping):
        return _base("UNMEASURABLE", reason="invalid_runner_state")
    valid = state.get("runner_kind") == "github-hosted" and state.get("pc_runner") is False and state.get("self_hosted") is False and state.get("paper_read_only") is True
    return _base(
        "PROVEN" if valid else "REJECTED",
        verdict="PC_NOT_A_RUNNER" if valid else "PC_RUNNER_PATH_PRESENT",
        runner_kind=state.get("runner_kind"),
        pc_runner=state.get("pc_runner"),
        self_hosted=state.get("self_hosted"),
    )


def git_sync_local_data_receipt(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    """Prove a sync checkpoint kept local SAFE data unchanged."""
    if not isinstance(before, Mapping) or not isinstance(after, Mapping) or not _sha(before.get("safe_manifest_sha")) or not _sha(after.get("safe_manifest_sha")):
        return _base("UNMEASURABLE", reason="safe_manifest_identity_missing")
    unchanged = before["safe_manifest_sha"].lower() == after["safe_manifest_sha"].lower() and before.get("safe_bytes") == after.get("safe_bytes")
    return _base(
        "PROVEN" if unchanged else "REJECTED",
        verdict="GIT_SYNC_DID_NOT_ALTER_LOCAL_SAFE" if unchanged else "GIT_SYNC_ALTERED_LOCAL_SAFE",
        before_manifest_sha=before["safe_manifest_sha"],
        after_manifest_sha=after["safe_manifest_sha"],
        before_safe_bytes=before.get("safe_bytes"),
        after_safe_bytes=after.get("safe_bytes"),
    )


def shard_publication_lag_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Measure SAFE publication delay from observed creation and publication times."""
    if not rows:
        return _base("MORE_DATA", reason="empty_shard_publication_history")
    lags: list[int] = []
    invalid: list[int] = []
    for index, row in enumerate(rows):
        created = row.get("created_ts_ms") if isinstance(row, Mapping) else None
        published = row.get("published_ts_ms") if isinstance(row, Mapping) else None
        if not _int(created) or not _int(published) or created < 0 or published < created:
            invalid.append(index)
        else:
            lags.append(published - created)
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="SAFE_SHARD_PUBLICATION_LAG_MEASURED" if not invalid else "SAFE_SHARD_PUBLICATION_TIMING_INVALID",
        lags_ms=lags,
        invalid_rows=invalid,
    )


def hosted_resume_outage_link_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Link a hosted resume receipt to an observed local outage record."""
    if not rows:
        return _base("MORE_DATA", reason="empty_hosted_resume_links")
    invalid = [
        index for index, row in enumerate(rows)
        if not isinstance(row, Mapping)
        or not str(row.get("hosted_run_id") or "").strip()
        or not str(row.get("resume_receipt_id") or "").strip()
        or not str(row.get("local_outage_ref") or "").strip()
    ]
    return _base(
        "PROVEN" if not invalid else "UNMEASURABLE",
        verdict="HOSTED_RESUME_LINKED_TO_LOCAL_OUTAGE" if not invalid else "HOSTED_RESUME_OUTAGE_LINK_MISSING",
        links=len(rows),
        invalid_rows=invalid,
    )


def receipt_cache_epoch_guard_receipt(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Reject receipt-cache collisions across phase epochs."""
    if not rows:
        return _base("MORE_DATA", reason="empty_receipt_cache")
    seen: dict[str, int] = {}
    invalid: list[int] = []
    for index, row in enumerate(rows):
        receipt_id = str(row.get("receipt_id") or "") if isinstance(row, Mapping) else ""
        epoch = row.get("phase_epoch") if isinstance(row, Mapping) else None
        if not receipt_id or not _int(epoch) or epoch <= 0 or (receipt_id in seen and seen[receipt_id] != epoch):
            invalid.append(index)
        else:
            seen[receipt_id] = epoch
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="RECEIPT_CACHE_EPOCH_GUARDED" if not invalid else "RECEIPT_CACHE_EPOCH_COLLISION",
        receipts=len(rows),
        invalid_rows=invalid,
    )


def interface_loss_receipt(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Require an interface network-loss observation to remain fail-closed."""
    if not events:
        return _base("MORE_DATA", reason="empty_interface_loss_events")
    invalid: list[int] = []
    for index, event in enumerate(events):
        if not isinstance(event, Mapping) or event.get("event") not in {"network_lost", "network_restored", "ui_state"} or event.get("fail_closed") is not True or event.get("real_execution") is not False:
            invalid.append(index)
    return _base(
        "PROVEN" if not invalid else "REJECTED",
        verdict="INTERFACE_LOSS_FAILS_CLOSED" if not invalid else "INTERFACE_LOSS_NOT_FAIL_CLOSED",
        events=len(events),
        invalid_rows=invalid,
    )


def schedule_saturation_receipt(*, scheduled: bool, dispatch_preserved: bool) -> dict[str, Any]:
    """A saturated hosted queue must preserve the scheduled run rather than drop it."""

    valid = bool(scheduled) and bool(dispatch_preserved)
    return _base("PROVEN" if valid else "REJECTED", verdict="SCHEDULE_PRESERVED" if valid else "SCHEDULE_DROPPED", fail_closed=not valid)


def concurrency_cancel_receipt(*, collection_active: bool, cancelled: bool, checkpoint_saved: bool) -> dict[str, Any]:
    """Concurrency cancellation may stop collection only after a SAFE checkpoint."""

    valid = not bool(collection_active) or (bool(cancelled) and bool(checkpoint_saved))
    return _base("PROVEN" if valid else "REJECTED", verdict="CONCURRENCY_CANCEL_SAFE" if valid else "CONCURRENCY_CANCEL_UNSAFE", fail_closed=not valid)


def publication_tag_collision_receipt(*, tag: Any, campaign_ids: Sequence[Any]) -> dict[str, Any]:
    """One publication tag must resolve to one campaign identity."""

    ids = {str(value).strip() for value in campaign_ids if str(value).strip()}
    valid = bool(str(tag).strip()) and len(ids) == 1
    return _base("PROVEN" if valid else "REJECTED", verdict="PUBLICATION_TAG_UNIQUE" if valid else "PUBLICATION_TAG_COLLISION", campaign_ids=sorted(ids), fail_closed=not valid)


def github_token_permissions_receipt(*, permissions: Sequence[Any]) -> dict[str, Any]:
    """Hosted workflow tokens must remain read-only and narrowly scoped."""

    allowed = {"contents:read", "actions:read", "metadata:read"}
    values = {str(value).strip().casefold() for value in permissions}
    valid = bool(values) and values <= allowed and not any(value.endswith(":write") for value in values)
    return _base("PROVEN" if valid else "REJECTED", verdict="GITHUB_TOKEN_READ_ONLY" if valid else "GITHUB_TOKEN_TOO_BROAD", permissions=sorted(values), fail_closed=not valid)


def hosted_runner_boundary_receipt(*, runner_kind: Any, self_hosted: bool, local_dependency: bool) -> dict[str, Any]:
    """CI evidence must come from GitHub-hosted runners without local dependencies."""

    valid = str(runner_kind).strip().casefold() == "github-hosted" and not bool(self_hosted) and not bool(local_dependency)
    return _base("PROVEN" if valid else "REJECTED", verdict="HOSTED_RUNNER_BOUNDED" if valid else "HOSTED_RUNNER_UNSAFE", fail_closed=not valid)


def fork_trigger_receipt(*, fork_event: bool, trusted_ref: bool, exact_sha: Any) -> dict[str, Any]:
    """A fork-triggered run is not an exact-SHA hosted proof unless explicitly trusted."""

    valid = not bool(fork_event) and bool(trusted_ref) and _sha(exact_sha)
    return _base("PROVEN" if valid else "REJECTED", verdict="FORK_TRIGGER_BOUNDED" if valid else "FORK_TRIGGER_UNTRUSTED", fail_closed=not valid)


def immutable_action_cache_receipt(*, cache_key: Any, immutable: bool, includes_code_sha: bool, mutable: bool) -> dict[str, Any]:
    """Action cache evidence must include code identity and be immutable."""

    valid = bool(str(cache_key).strip()) and bool(immutable) and bool(includes_code_sha) and not bool(mutable)
    return _base("PROVEN" if valid else "REJECTED", verdict="ACTION_CACHE_IMMUTABLE" if valid else "ACTION_CACHE_MUTABLE", fail_closed=not valid)


def upload_failure_exit_receipt(*, upload_failed: bool, job_success: bool) -> dict[str, Any]:
    """An artifact upload failure must fail the job, never produce a green receipt."""

    valid = not bool(upload_failed) or not bool(job_success)
    return _base("PROVEN" if valid else "REJECTED", verdict="UPLOAD_FAILURE_PROPAGATED" if valid else "UPLOAD_FAILURE_HIDDEN", fail_closed=not valid)


def retry_publication_idempotency_receipt(*, publication_ids: Sequence[Any], tag: Any) -> dict[str, Any]:
    """Retries must not publish two different identities under one tag."""

    ids = [str(value).strip() for value in publication_ids]
    valid = bool(str(tag).strip()) and bool(ids) and len(set(ids)) == 1
    return _base("PROVEN" if valid else "REJECTED", verdict="PUBLICATION_RETRY_IDEMPOTENT" if valid else "PUBLICATION_RETRY_DUPLICATED", fail_closed=not valid)


def hosted_rate_bound_receipt(*, request_count: Any, rate_limit: Any, throttled: bool) -> dict[str, Any]:
    """Hosted API use must stay within the declared read-only rate bound."""

    valid = _int(request_count) and _int(rate_limit) and request_count >= 0 and rate_limit >= 0 and (request_count <= rate_limit or bool(throttled))
    return _base("PROVEN" if valid else "REJECTED", verdict="HOSTED_RATE_BOUNDED" if valid else "HOSTED_RATE_EXCEEDED", fail_closed=not valid)


def catalog_commit_loop_receipt(*, catalog_sha: Any, commit_sha: Any, loop_count: Any, max_loops: Any) -> dict[str, Any]:
    """A catalog-triggered workflow must converge and remain bounded."""

    valid = _sha(catalog_sha) and _sha(commit_sha) and _int(loop_count) and _int(max_loops) and 0 <= loop_count <= max_loops
    return _base("PROVEN" if valid else "REJECTED", verdict="CATALOG_TRIGGER_BOUNDED" if valid else "CATALOG_TRIGGER_LOOP", catalog_sha=catalog_sha, commit_sha=commit_sha, loop_count=loop_count, max_loops=max_loops, fail_closed=not valid)


def journal_flush_receipt(*, records: Sequence[Mapping[str, Any]], flushed_sequence: Any) -> dict[str, Any]:
    """A completed hosted run must flush every contiguous journal record."""

    if not records or not _int(flushed_sequence) or flushed_sequence < 0:
        return _base("UNMEASURABLE", reason="journal_flush_evidence_missing")
    sequences = [row.get("sequence") for row in records if isinstance(row, Mapping)]
    valid = len(sequences) == len(records) and all(_int(value) and value >= 0 for value in sequences) and sorted(sequences) == list(range(0, len(records))) and flushed_sequence == len(records) - 1
    return _base("PROVEN" if valid else "REJECTED", verdict="JOURNAL_FLUSH_COMPLETE" if valid else "JOURNAL_FLUSH_INCOMPLETE", record_count=len(records), flushed_sequence=flushed_sequence, fail_closed=not valid)


def segment_timeout_boundary_receipt(*, completed: bool, checkpoint_saved: bool, partial_manifest: bool, cutoff_preserved: bool) -> dict[str, Any]:
    """A timeout may leave only a checkpointed, manifest-bound partial segment."""

    valid = bool(completed) or (bool(checkpoint_saved) and bool(partial_manifest) and bool(cutoff_preserved))
    return _base("PROVEN" if valid else "REJECTED", verdict="SEGMENT_TIMEOUT_BOUNDARY_SAFE" if valid else "SEGMENT_TIMEOUT_LOST_STATE", completed=bool(completed), checkpoint_saved=bool(checkpoint_saved), partial_manifest=bool(partial_manifest), cutoff_preserved=bool(cutoff_preserved), fail_closed=not valid)


def log_secret_redaction_receipt(*, messages: Sequence[Any], forbidden_fragments: Sequence[Any]) -> dict[str, Any]:
    """Verbose hosted logs must not expose configured secret fragments."""

    fragments = [str(value) for value in forbidden_fragments if str(value)]
    leaked = [index for index, message in enumerate(messages) if any(fragment in str(message) for fragment in fragments)]
    valid = not leaked
    return _base("PROVEN" if valid else "REJECTED", verdict="LOG_SECRETS_REDACTED" if valid else "LOG_SECRET_LEAK", messages=len(messages), leaked_rows=leaked, fail_closed=not valid)


def actions_pagination_receipt(*, pages: Sequence[Mapping[str, Any]], total_count: Any) -> dict[str, Any]:
    """Actions pagination must prove that no final page was silently omitted."""

    if not pages or not _int(total_count) or total_count < 0:
        return _base("UNMEASURABLE", reason="actions_pagination_evidence_missing")
    invalid = []
    seen = 0
    for index, page in enumerate(pages):
        if not isinstance(page, Mapping) or page.get("page") != index or not _int(page.get("count")) or page.get("count") < 0:
            invalid.append(index)
        else:
            seen += page["count"]
    valid = not invalid and seen == total_count
    return _base("PROVEN" if valid else "UNMEASURABLE", verdict="ACTIONS_PAGINATION_COMPLETE" if valid else "ACTIONS_PAGINATION_INCOMPLETE", pages=len(pages), observed_count=seen, total_count=total_count, invalid_pages=invalid)


def release_transient_receipt(*, status: Any, retry_required: bool, definitive_not_found: bool) -> dict[str, Any]:
    """Transient release errors must not be recorded as permanent absence."""

    transient = str(status).strip().casefold() in {"timeout", "rate_limited", "server_error", "unavailable"}
    valid = (transient and bool(retry_required) and not bool(definitive_not_found)) or (not transient and bool(definitive_not_found) == (str(status).strip().casefold() == "not_found"))
    return _base("PROVEN" if valid else "REJECTED", verdict="RELEASE_TRANSIENT_RETRIABLE" if valid else "RELEASE_TRANSIENT_MISCLASSIFIED", observed_status=status, retry_required=bool(retry_required), definitive_not_found=bool(definitive_not_found), fail_closed=not valid)


def concurrent_queue_alert_receipt(*, queue_depth: Any, capacity: Any, alert_emitted: bool) -> dict[str, Any]:
    """An over-capacity hosted queue must emit a visible alert."""

    valid = _int(queue_depth) and _int(capacity) and queue_depth >= 0 and capacity >= 0 and (queue_depth <= capacity or bool(alert_emitted))
    return _base("PROVEN" if valid else "REJECTED", verdict="QUEUE_CAPACITY_ALERTED" if valid else "QUEUE_CAPACITY_UNALERTED", queue_depth=queue_depth, capacity=capacity, alert_emitted=bool(alert_emitted), fail_closed=not valid)


def scheduled_branch_receipt(*, workflow_ref: Any, scheduled_ref: Any, default_branch: Any) -> dict[str, Any]:
    """Scheduled workflows must resolve to the protected default branch."""

    valid = str(workflow_ref).strip() == str(scheduled_ref).strip() == str(default_branch).strip() and bool(str(default_branch).strip())
    return _base("PROVEN" if valid else "REJECTED", verdict="SCHEDULED_BRANCH_BOUNDED" if valid else "SCHEDULED_BRANCH_MISMATCH", workflow_ref=workflow_ref, scheduled_ref=scheduled_ref, default_branch=default_branch, fail_closed=not valid)


def action_pin_receipt(*, actions: Sequence[Any]) -> dict[str, Any]:
    """Third-party actions must be pinned to immutable commit SHAs."""

    invalid = [index for index, action in enumerate(actions) if not isinstance(action, str) or "@" not in action or not re.fullmatch(r"[0-9a-fA-F]{40}", action.rsplit("@", 1)[1])]
    valid = bool(actions) and not invalid
    return _base("PROVEN" if valid else "REJECTED", verdict="ACTIONS_PINNED" if valid else "ACTION_TAG_UNPINNED", actions=len(actions), invalid_actions=invalid, fail_closed=not valid)


def artifact_retention_receipt(*, artifact_retention_days: Any, release_retention_days: Any, released: bool, release_asset_present: bool) -> dict[str, Any]:
    """A durable release asset must not be confused with expiring run artifacts."""

    valid = _int(artifact_retention_days) and _int(release_retention_days) and artifact_retention_days >= 0 and release_retention_days >= artifact_retention_days and (not released or bool(release_asset_present))
    return _base("PROVEN" if valid else "REJECTED", verdict="ARTIFACT_RETENTION_DISTINGUISHED" if valid else "ARTIFACT_RETENTION_CONFUSED", artifact_retention_days=artifact_retention_days, release_retention_days=release_retention_days, released=bool(released), release_asset_present=bool(release_asset_present), fail_closed=not valid)


__all__ = [
    "collect_phase_epoch_receipt",
    "cloud_campaign_readonly_receipt",
    "host_receipt_diagnostics_receipt",
    "cloud_head_local_binary_receipt",
    "pc_runner_involuntary_receipt",
    "git_sync_local_data_receipt",
    "shard_publication_lag_receipt",
    "hosted_resume_outage_link_receipt",
    "receipt_cache_epoch_guard_receipt",
    "interface_loss_receipt",
    "schedule_saturation_receipt",
    "concurrency_cancel_receipt",
    "publication_tag_collision_receipt",
    "github_token_permissions_receipt",
    "hosted_runner_boundary_receipt",
    "fork_trigger_receipt",
    "immutable_action_cache_receipt",
    "upload_failure_exit_receipt",
    "retry_publication_idempotency_receipt",
    "hosted_rate_bound_receipt",
    "catalog_commit_loop_receipt",
    "journal_flush_receipt",
    "segment_timeout_boundary_receipt",
    "log_secret_redaction_receipt",
    "actions_pagination_receipt",
    "release_transient_receipt",
    "concurrent_queue_alert_receipt",
    "scheduled_branch_receipt",
    "action_pin_receipt",
    "artifact_retention_receipt",
]
