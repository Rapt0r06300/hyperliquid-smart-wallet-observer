#!/usr/bin/env python3
"""Refresh a stale, unleased COLLECT campaign after collector code changes.

Only non-productive current-epoch collection manifests are eligible. Any lease,
durable output, productive completed unit, terminal evidence for a non-FAILED
outcome, or phase mismatch makes the operation a no-op or hard refusal. The previous manifest is archived
byte-for-byte before mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

COLLECT_KINDS = {
    "market_collection",
    "copy_vault_collection",
    "official_archive_collection",
    "event_intelligence_collection",
}
REFRESHABLE_STATUSES = {"PENDING", "CONTINUATION_REQUIRED", "FAILED", "STUCK"}
RUNTIME_CURSOR_KEYS = {
    "checkpoint_id",
    "last_run_id",
    "generation",
    "handoff_phase_epoch",
    "predecessor_run_id",
    "handoff_generation",
    "requested_handoff_at_utc",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=path.name + ".", suffix=".tmp", text=True
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _has_productive_work(row: dict[str, Any]) -> bool:
    if row.get("outputs"):
        return True
    completed = row.get("completed_units") or {}
    if not isinstance(completed, dict):
        return True
    for unit in completed.values():
        result = unit.get("result") if isinstance(unit, dict) else None
        if not isinstance(result, dict):
            return True
        if str(result.get("status") or "") != "FAILED":
            return True
    # A terminal digest on a FAILED campaign only certifies the failure itself.
    # It must not freeze a retry when every completed unit is also FAILED and
    # no durable output was produced.
    if row.get("terminal_evidence_digest") and str(row.get("status") or "") != "FAILED":
        return True
    return False


def refresh(
    *,
    manifest_path: Path,
    history_dir: Path,
    code_sha: str,
    config_sha256: str,
    work_plan_sha256: str,
    expected_phase_epoch: int,
) -> dict[str, Any]:
    raw_text = manifest_path.read_text(encoding="utf-8")
    row = json.loads(raw_text)
    if not isinstance(row, dict):
        raise SystemExit("campaign manifest must be an object")
    if row.get("schema_version") != "alina.resumable_campaign.v2":
        raise SystemExit("only resumable campaign v2 may be refreshed")
    if row.get("creation_phase") != "COLLECT":
        raise SystemExit("only COLLECT campaigns may be refreshed by this tool")
    if row.get("kind") not in COLLECT_KINDS:
        raise SystemExit("unsupported collection campaign kind")
    if (
        row.get("paper_only") is not True
        or row.get("read_only") is not True
        or row.get("real_execution") is not False
    ):
        raise SystemExit("collection campaign lost paper/read-only guards")
    if int(row.get("phase_epoch") or 0) != int(expected_phase_epoch):
        raise SystemExit("phase epoch changed")
    if row.get("lease") is not None:
        return {
            "refreshed": False,
            "reason": "leased_campaign_preserved",
            "campaign_id": row.get("campaign_id"),
        }

    status = str(row.get("status") or "")
    if status not in REFRESHABLE_STATUSES:
        return {
            "refreshed": False,
            "reason": "status_not_refreshable",
            "status": status,
            "campaign_id": row.get("campaign_id"),
        }
    if _has_productive_work(row):
        return {
            "refreshed": False,
            "reason": "durable_or_productive_work_preserved",
            "status": status,
            "campaign_id": row.get("campaign_id"),
        }

    if not re.fullmatch(r"[0-9a-f]{40}", code_sha):
        raise SystemExit("new code SHA must be an exact 40-hex Git commit")
    for name, value in (
        ("config_sha256", config_sha256),
        ("work_plan_sha256", work_plan_sha256),
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(value)):
            raise SystemExit(f"{name} must be an exact SHA-256")

    old_code_sha = str(row.get("code_sha") or "")
    if old_code_sha == code_sha:
        return {
            "refreshed": False,
            "reason": "code_sha_unchanged",
            "status": status,
            "campaign_id": row.get("campaign_id"),
        }

    source_digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
    archive_path = history_dir / (
        f"{manifest_path.stem}.{status.lower()}.{old_code_sha[:12]}.{source_digest}.json"
    )
    if archive_path.exists():
        if archive_path.read_text(encoding="utf-8") != raw_text:
            raise SystemExit("campaign history collision")
    else:
        _atomic_write(archive_path, raw_text)

    cursor = {
        key: value
        for key, value in dict(row.get("cursor") or {}).items()
        if key not in RUNTIME_CURSOR_KEYS
    }
    history = list(row.get("history") or [])
    history.append(
        {
            "event": "refresh_collect_after_code_fix",
            "at": _now(),
            "archived_manifest": archive_path.as_posix(),
            "archived_manifest_sha256": source_digest,
            "prior_code_sha": old_code_sha,
            "prior_status": status,
            "prior_status_reason": row.get("status_reason"),
        }
    )
    updated = {
        **row,
        "code_sha": code_sha,
        "config_sha256": config_sha256,
        "work_plan_sha256": work_plan_sha256,
        "status": "PENDING",
        "status_reason": "refresh_collect_after_code_fix",
        "updated_at": _now(),
        "chunk_index": 0,
        "attempts": int(row.get("attempts") or 0) + 1,
        "consecutive_failures": 0,
        "no_progress_count": 0,
        "next_due_at": None,
        "cursor": cursor,
        "completed_units": {},
        "lease": None,
        "outputs": [],
        "checkpoint_lineage": [],
        "terminal_evidence_digest": None,
        "history": history,
    }
    _atomic_write(
        manifest_path,
        json.dumps(updated, sort_keys=True, indent=2) + "\n",
    )
    return {
        "refreshed": True,
        "campaign_id": updated.get("campaign_id"),
        "prior_code_sha": old_code_sha,
        "new_code_sha": code_sha,
        "archive_path": archive_path.as_posix(),
        "archive_sha256": source_digest,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--history-dir", default="catalog/campaign-history")
    parser.add_argument("--code-sha", required=True)
    parser.add_argument("--config-sha256", required=True)
    parser.add_argument("--work-plan-sha256", required=True)
    parser.add_argument("--expected-phase-epoch", type=int, required=True)
    args = parser.parse_args()
    result = refresh(
        manifest_path=Path(args.manifest),
        history_dir=Path(args.history_dir),
        code_sha=args.code_sha,
        config_sha256=args.config_sha256,
        work_plan_sha256=args.work_plan_sha256,
        expected_phase_epoch=args.expected_phase_epoch,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
