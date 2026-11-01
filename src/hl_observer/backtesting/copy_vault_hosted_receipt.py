"""Build a strict, read-only receipt for one GitHub-hosted CI run.

This receipt proves only that the hosted laboratory checks completed and that
the uploaded reports are bound to the exact commit SHA.  It is deliberately
not a task-completion receipt: the tasklist's ``closure_allowed`` value and
the explicit limitations remain in the output, and no economic, causal,
checkpoint-resume, or SAFE restoration claim is inferred from a green CI.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any


SCHEMA = "hypersmart.copy_vault_hosted_ci_receipt.v1"
PROOF_STATUS = "HOSTED_CI_VERIFIED"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_HASH64_RE = re.compile(r"^[0-9a-f]{64}$")


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def _positive_number(value: object, label: str) -> str:
    text = _text(value, label)
    if not text.isdigit() or int(text) < 1:
        raise ValueError(f"{label} must be a positive decimal identifier")
    return text


def _artifact(value: Mapping[str, Any], *, head_sha: str) -> dict[str, str]:
    artifact_id = _positive_number(value.get("id"), "artifact id")
    name = _text(value.get("name"), "artifact name")
    digest = value.get("digest")
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest.lower()):
        raise ValueError(f"artifact digest for {name} must be sha256:<64 hex chars>")
    if head_sha not in name.lower():
        raise ValueError(f"artifact {name} is not bound to the exact head SHA")
    return {"id": artifact_id, "name": name, "digest": digest.lower()}


def build_hosted_ci_receipt(
    *,
    repository: str,
    workflow: str,
    event: str,
    ref: str,
    head_sha: str,
    run_id: str,
    run_attempt: str,
    status: str,
    conclusion: str,
    pytest_exit_code: int,
    junit_artifact: Mapping[str, Any],
    closure_artifact: Mapping[str, Any],
    tasklist_report: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a validated receipt; never writes files or changes task state."""

    normalized_sha = _text(head_sha, "head_sha").lower()
    if not _SHA_RE.fullmatch(normalized_sha):
        raise ValueError("head_sha must be a 40-character commit SHA")
    if _text(status, "status").lower() != "completed":
        raise ValueError("hosted CI receipt requires a completed run")
    if _text(conclusion, "conclusion").lower() != "success":
        raise ValueError("hosted CI receipt requires a successful run")
    if pytest_exit_code != 0:
        raise ValueError("hosted CI receipt requires pytest exit code 0")

    report = dict(tasklist_report)
    if not isinstance(tasklist_report, Mapping):
        raise ValueError("tasklist_report must be an object")
    if report.get("expected_head_sha", "").lower() != normalized_sha:
        raise ValueError("tasklist report is not bound to the exact head SHA")
    global_report = report.get("global")
    if not isinstance(global_report, Mapping):
        raise ValueError("tasklist report global section is missing")
    total = global_report.get("total")
    done = global_report.get("done")
    testing = global_report.get("testing")
    blocked = global_report.get("blocked")
    closure_allowed = global_report.get("closure_allowed")
    if total != 10 or any(not isinstance(value, int) for value in (done, testing, blocked)):
        raise ValueError("tasklist report must contain the ten-task integer summary")
    if done < 0 or testing < 0 or blocked < 0 or done + testing != total:
        raise ValueError("tasklist report global counts are inconsistent")
    if not isinstance(closure_allowed, bool):
        raise ValueError("tasklist report closure_allowed must be boolean")
    if closure_allowed != (done == total and testing == 0):
        raise ValueError("tasklist report closure_allowed contradicts its counts")
    task_rows = report.get("tasks")
    if not isinstance(task_rows, list) or len(task_rows) != total:
        raise ValueError("tasklist report must contain ten task contract rows")
    task_contract_sha256: dict[str, str] = {}
    for row in task_rows:
        if not isinstance(row, Mapping):
            raise ValueError("tasklist contract row must be an object")
        task_id = _text(row.get("task_id"), "tasklist task_id")
        contract_sha256 = row.get("closure_contract_sha256")
        if (
            not isinstance(contract_sha256, str)
            or not _HASH64_RE.fullmatch(contract_sha256.lower())
        ):
            raise ValueError(f"task {task_id} has an invalid closure contract SHA-256")
        if task_id in task_contract_sha256:
            raise ValueError(f"duplicate task contract row: {task_id}")
        task_contract_sha256[task_id] = contract_sha256.lower()

    artifacts = [
        _artifact(junit_artifact, head_sha=normalized_sha),
        _artifact(closure_artifact, head_sha=normalized_sha),
    ]
    if artifacts[0]["id"] == artifacts[1]["id"]:
        raise ValueError("JUnit and closure artifacts must have distinct IDs")

    return {
        "schema": SCHEMA,
        "proof_status": PROOF_STATUS,
        "repository": _text(repository, "repository"),
        "workflow": _text(workflow, "workflow"),
        "event": _text(event, "event"),
        "ref": _text(ref, "ref"),
        "run": {
            "id": _positive_number(run_id, "run_id"),
            "attempt": _positive_number(run_attempt, "run_attempt"),
            "status": "completed",
            "conclusion": "success",
            "head_sha": normalized_sha,
        },
        "artifacts": artifacts,
        "paper_read_only": True,
        "real_execution": False,
        "claims": {
            "exact_sha_bound_ci_receipt": True,
            "tasklist_audited": True,
        },
        "tasklist": {
            "schema": report.get("schema"),
            "expected_head_sha": normalized_sha,
            "global": {
                "done": done,
                "testing": testing,
                "blocked": blocked,
                "total": total,
                "closure_allowed": closure_allowed,
            },
            "closure_allowed": closure_allowed,
        },
        "task_contract_sha256": task_contract_sha256,
        "limitations": [
            "CI success does not prove economic performance or OOS/FORWARD validity.",
            "CI success does not prove a checkpoint interruption/resume.",
            "CI success does not prove a causal LIVE_WS fill or L4 pairing.",
            "CI success does not prove SAFE shard restoration or quarantine preservation.",
        ],
    }


__all__ = ["PROOF_STATUS", "SCHEMA", "build_hosted_ci_receipt"]
