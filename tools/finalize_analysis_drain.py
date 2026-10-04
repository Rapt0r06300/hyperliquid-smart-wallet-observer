#!/usr/bin/env python3
"""Fail-closed finalizer for the bounded COLLECT -> ANALYZE drain barrier."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
from typing import Any

ACTIVE = {"PENDING", "RUNNING", "CONTINUATION_REQUIRED", "STUCK"}
COLLECTION_KINDS = {
    "market_collection",
    "copy_vault_collection",
    "official_archive_collection",
    "event_intelligence_collection",
}


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _terminal_digest(row: dict[str, Any], status: str, reason: str) -> str:
    payload = {
        "campaign_id": row.get("campaign_id"),
        "status": status,
        "reason": reason,
        "completed_units": row.get("completed_units") or {},
        "checkpoint_lineage": row.get("checkpoint_lineage") or [],
    }
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


def _lease_is_live(row: dict[str, Any], now: datetime) -> bool:
    lease = row.get("lease")
    if not isinstance(lease, dict) or not lease.get("expires_at"):
        return False
    try:
        return _parse(str(lease["expires_at"])) > now
    except (TypeError, ValueError):
        return False


def finalize(
    *,
    phase_path: Path,
    campaign_root: Path,
    drain_grace_s: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or _now()
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    if phase.get("phase") != "ANALYZE":
        return {"status": "INERT", "changed": 0, "remaining_active": 0}
    source_epoch = phase.get("source_collection_epoch")
    cutoff_raw = phase.get("collection_cutoff_at_utc")
    if isinstance(source_epoch, bool) or not isinstance(source_epoch, int) or source_epoch < 1:
        raise SystemExit("invalid source collection epoch")
    if not cutoff_raw:
        raise SystemExit("ANALYZE drain requires collection cutoff")
    cutoff = _parse(str(cutoff_raw))
    deadline = cutoff + timedelta(seconds=max(60, int(drain_grace_s)))

    changed = 0
    remaining: list[str] = []
    finalized: list[dict[str, str]] = []
    for path in sorted(campaign_root.glob("*.json")):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(row, dict):
            continue
        if row.get("schema_version") != "alina.resumable_campaign.v2":
            continue
        if row.get("creation_phase") != "COLLECT":
            continue
        if int(row.get("phase_epoch") or 0) != source_epoch:
            continue
        if row.get("kind") not in COLLECTION_KINDS:
            continue
        status = str(row.get("status") or "")
        if status not in ACTIVE:
            continue

        # A worker claimed before the cutoff may finish while its bounded lease is
        # still live. No new source-epoch lease can be acquired in ANALYZE.
        if _lease_is_live(row, current) and current <= deadline:
            remaining.append(str(row.get("campaign_id") or path.stem))
            continue

        # Once ANALYZE owns the phase, an inactive/expired source-epoch lease can
        # never be renewed. Keeping such a manifest active until the six-hour
        # grace deadline only deadlocks DRAIN. Close it immediately from the
        # durable checkpoint already present (if any). A still-running worker
        # with an expired lease cannot checkpoint because verify_lease() fails.
        completed = row.get("completed_units")
        has_completed = isinstance(completed, dict) and bool(completed)
        terminal_status = "PARTIAL" if has_completed else "UNAVAILABLE"
        if current <= deadline:
            reason = (
                "analysis_drain_inactive_lease_with_checkpoint"
                if has_completed
                else "analysis_drain_inactive_lease_without_checkpoint"
            )
        else:
            reason = (
                "analysis_drain_deadline_expired_with_checkpoint"
                if has_completed
                else "analysis_drain_deadline_expired_without_checkpoint"
            )
        previous = status
        timestamp = current.isoformat().replace("+00:00", "Z")
        row["status"] = terminal_status
        row["status_reason"] = reason
        row["lease"] = None
        row["next_due_at"] = None
        row["updated_at"] = timestamp
        row["terminal_evidence_digest"] = _terminal_digest(row, terminal_status, reason)
        history = row.get("history")
        if not isinstance(history, list):
            history = []
            row["history"] = history
        history.append(
            {
                "at": timestamp,
                "from": previous,
                "to": terminal_status,
                "reason": reason,
                "event": "ANALYSIS_DRAIN_FINALIZED",
                "source_collection_epoch": source_epoch,
                "collection_cutoff_at_utc": cutoff_raw,
            }
        )
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(row, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
        changed += 1
        finalized.append(
            {
                "campaign_id": str(row.get("campaign_id") or path.stem),
                "status": terminal_status,
            }
        )

    return {
        "status": "FINALIZED" if changed else ("WAITING" if remaining else "CLOSED"),
        "changed": changed,
        "remaining_active": len(remaining),
        "remaining_campaign_ids": remaining,
        "finalized": finalized,
        "source_collection_epoch": source_epoch,
        "cutoff": cutoff_raw,
        "drain_deadline_utc": deadline.isoformat().replace("+00:00", "Z"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-path", default="control/alina-phase.json")
    parser.add_argument("--campaign-root", default="catalog/campaigns")
    parser.add_argument("--drain-grace-s", type=int, default=21600)
    args = parser.parse_args()
    result = finalize(
        phase_path=Path(args.phase_path),
        campaign_root=Path(args.campaign_root),
        drain_grace_s=args.drain_grace_s,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
