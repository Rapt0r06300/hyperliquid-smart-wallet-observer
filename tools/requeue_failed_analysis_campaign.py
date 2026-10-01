#!/usr/bin/env python3
"""Requeue one failed ANALYZE campaign after a verified code change.

The prior manifest is archived byte-for-byte before mutation. Collection
campaigns are never eligible. A CONTINUATION_REQUIRED campaign is refreshable
only for the narrow durable-publication failure case, where no useful durable
checkpoint was published. The frozen phase/source epoch/dataset selection
identity must remain unchanged.
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

ANALYSIS_KINDS = {
    "replay",
    "backtest",
    "oos",
    "forward_paper",
    "module_pnl_proof",
    "scoreboard",
}
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


def requeue(
    *,
    manifest_path: Path,
    history_dir: Path,
    code_sha: str,
    config_sha256: str,
    work_plan_sha256: str,
    expected_phase_epoch: int,
    expected_analysis_stage: str,
    expected_source_collection_epoch: int,
    expected_dataset_selection_id: str,
) -> dict[str, Any]:
    raw_text = manifest_path.read_text(encoding="utf-8")
    row = json.loads(raw_text)
    if not isinstance(row, dict):
        raise SystemExit("campaign manifest must be an object")

    if row.get("schema_version") != "alina.resumable_campaign.v2":
        raise SystemExit("only resumable campaign v2 may be requeued")
    if row.get("creation_phase") != "ANALYZE":
        raise SystemExit("collection/idle campaigns may never be requeued by this tool")
    if row.get("kind") not in ANALYSIS_KINDS:
        raise SystemExit("unknown analysis campaign kind")
    if row.get("paper_only") is not True or row.get("read_only") is not True:
        raise SystemExit("analysis campaign lost paper/read-only guards")
    if row.get("real_execution") is not False:
        raise SystemExit("real execution is forbidden")

    # Periodic creation may observe a campaign after another worker has claimed
    # it. RUNNING/terminal state is authoritative and must be a harmless no-op,
    # not a failed attempt to rewrite a live lease.  The sole continuation case
    # that can be refreshed is a failed durable publication: the economic unit
    # completed, but the canonical receipt was not committed, so rerunning after
    # a code fix is required and does not discard a valid durable checkpoint.
    current_status = str(row.get("status") or "")
    continuation_publication_failure = (
        current_status == "CONTINUATION_REQUIRED"
        and str(row.get("status_reason") or "") == "durable_publication_failed"
    )
    if current_status not in {"FAILED", "PENDING"} and not continuation_publication_failure:
        return {
            "requeued": False,
            "reason": "status_not_refreshable",
            "status": current_status,
            "campaign_id": row.get("campaign_id"),
        }
    if row.get("lease") is not None:
        raise SystemExit("cannot refresh a leased analysis campaign")
    if continuation_publication_failure:
        completed = row.get("completed_units") or {}
        if not isinstance(completed, dict) or not completed:
            raise SystemExit("durable publication continuation lacks failure checkpoint")
        for unit in completed.values():
            result = unit.get("result") if isinstance(unit, dict) else None
            if (
                not isinstance(result, dict)
                or result.get("status") != "FAILED"
                or result.get("reason") != "durable_publication_failed"
            ):
                raise SystemExit(
                    "durable publication continuation contains non-publication work"
                )

    if int(row.get("phase_epoch") or 0) != int(expected_phase_epoch):
        raise SystemExit("phase epoch changed")
    if str(row.get("analysis_stage") or "") != str(expected_analysis_stage):
        raise SystemExit("analysis stage changed")
    if int(row.get("source_collection_epoch") or 0) != int(
        expected_source_collection_epoch
    ):
        raise SystemExit("source collection epoch changed")
    if str(row.get("dataset_selection_id") or "") != str(
        expected_dataset_selection_id
    ):
        raise SystemExit("dataset selection identity changed")

    if not re.fullmatch(r"[0-9a-f]{40}", code_sha):
        raise SystemExit("new code SHA must be an exact 40-hex Git commit")
    for name, value in (
        ("config_sha256", config_sha256),
        ("work_plan_sha256", work_plan_sha256),
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(value)):
            raise SystemExit(f"{name} must be an exact SHA-256")

    status = str(row.get("status") or "")
    old_code_sha = str(row.get("code_sha") or "")
    if status == "PENDING" and (
        row.get("completed_units")
        or row.get("checkpoint_lineage")
        or row.get("terminal_evidence_digest")
    ):
        # Durable work is authoritative. The periodic creator must neither
        # rewrite it nor fail the whole orchestration pass merely because a
        # newer code SHA exists. A worker/controller or an explicit recovery
        # transition owns what happens next.
        return {
            "requeued": False,
            "reason": "pending_durable_work_preserved",
            "status": status,
            "campaign_id": row.get("campaign_id"),
        }
    if old_code_sha == code_sha:
        return {
            "requeued": False,
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

    history = list(row.get("history") or [])
    refresh_event = (
        "retry_after_code_fix"
        if status in {"FAILED", "CONTINUATION_REQUIRED"}
        else "refresh_pending_after_code_fix"
    )
    history.append(
        {
            "event": refresh_event,
            "at": _now(),
            "archived_manifest": archive_path.as_posix(),
            "archived_manifest_sha256": source_digest,
            "prior_code_sha": old_code_sha,
            "prior_status": status,
            "prior_status_reason": row.get("status_reason"),
            "prior_terminal_evidence_digest": row.get("terminal_evidence_digest"),
        }
    )
    cursor = {
        key: value
        for key, value in dict(row.get("cursor") or {}).items()
        if key not in RUNTIME_CURSOR_KEYS
    }

    updated = {
        **row,
        "code_sha": code_sha,
        "config_sha256": config_sha256,
        "work_plan_sha256": work_plan_sha256,
        "status": "PENDING",
        "status_reason": refresh_event,
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
        "requeued": True,
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
    parser.add_argument("--expected-analysis-stage", required=True)
    parser.add_argument("--expected-source-collection-epoch", type=int, required=True)
    parser.add_argument("--expected-dataset-selection-id", required=True)
    args = parser.parse_args()
    result = requeue(
        manifest_path=Path(args.manifest),
        history_dir=Path(args.history_dir),
        code_sha=args.code_sha,
        config_sha256=args.config_sha256,
        work_plan_sha256=args.work_plan_sha256,
        expected_phase_epoch=args.expected_phase_epoch,
        expected_analysis_stage=args.expected_analysis_stage,
        expected_source_collection_epoch=args.expected_source_collection_epoch,
        expected_dataset_selection_id=args.expected_dataset_selection_id,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
