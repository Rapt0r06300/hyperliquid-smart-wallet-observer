#!/usr/bin/env python3
"""Produce a durable, fail-closed campaign watchdog receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

PENDING_CONTROLLER_SLO_SECONDS = 15 * 60


def parse(value):
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _write_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, sort_keys=True, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _run_state(run_id: str) -> tuple[str, str]:
    if not run_id:
        return "missing", ""
    try:
        cp = subprocess.run(
            ["gh", "run", "view", run_id, "--json", "status,conclusion"],
            text=True,
            capture_output=True,
            check=False,
        )
        if cp.returncode != 0:
            return "unknown", (cp.stderr or "").strip()[-300:]
        payload = json.loads(cp.stdout or "{}")
        return str(payload.get("status") or "unknown"), str(payload.get("conclusion") or "")
    except (OSError, ValueError):
        return "unknown", "gh_unavailable"


def _reconcile_finished_owner(
    row: dict,
    now: datetime,
    *,
    run_state=_run_state,
) -> bool:
    """Revoke a lease whose GitHub owner run has already terminated.

    A GitHub-hosted worker cannot make further progress after its owning run is
    completed. Keeping that lease alive until its wall-clock TTL expires can
    stall ANALYZE for hours. Preserve the failed ownership evidence, clear the
    lease, and mark the campaign STUCK so the canonical controller/proof
    workflow can reconcile or retry from durable state.
    """
    if row.get("schema_version") != "alina.resumable_campaign.v2":
        return False
    if str(row.get("status") or "") not in {
        "PENDING",
        "RUNNING",
        "CONTINUATION_REQUIRED",
        "STUCK",
    }:
        return False
    lease = row.get("lease")
    if not isinstance(lease, dict):
        return False
    owner = (
        lease.get("owner_run_id")
        or lease.get("owner")
        or lease.get("owner_id")
    )
    if not owner:
        return False
    owner_status, owner_conclusion = run_state(str(owner))
    if owner_status != "completed":
        return False

    previous_status = str(row.get("status") or "")
    previous_lease = dict(lease)
    timestamp = now.isoformat().replace("+00:00", "Z")
    reason = "OWNER_RUN_COMPLETED_WITH_ACTIVE_LEASE"
    row["lease"] = None
    row["status"] = "STUCK"
    row["status_reason"] = reason
    row["stuck_reason"] = reason
    row["updated_at"] = timestamp
    row.setdefault("history", []).append({
        "at_utc": timestamp,
        "event": "WATCHDOG_OWNER_RUN_TERMINATED",
        "previous_status": previous_status,
        "previous_lease": previous_lease,
        "owner_run_id": str(owner),
        "owner_run_status": owner_status,
        "owner_run_conclusion": owner_conclusion,
        "reason": reason,
    })
    return True


def _dispatch_successor(row: dict, repository: str, now: datetime) -> tuple[bool, str]:
    campaign_id = str(row.get("campaign_id") or "")
    cursor = row.get("cursor") if isinstance(row.get("cursor"), dict) else {}
    marker = cursor.get("successor_dispatch_at_utc")
    if marker:
        try:
            if parse(marker) + timedelta(minutes=20) > now:
                return False, "dispatch_recent"
        except (TypeError, ValueError):
            pass
    predecessor = str(cursor.get("last_run_id") or "")
    status, detail = _run_state(predecessor)
    if predecessor and status != "completed":
        return False, "predecessor_active"
    command = [
        "gh", "workflow", "run", "resumable-campaign-worker.yml",
        "--repo", repository,
        "--ref", "main",
        "-f", f"campaign_id={campaign_id}",
        "-f", f"phase_epoch={row.get('phase_epoch')}",
        "-f", f"generation={int(row.get('chunk_index') or 0)}",
        "-f", f"predecessor_run_id={predecessor or 'unknown'}",
        "-f", f"requested_handoff_at_utc={now.isoformat().replace('+00:00', 'Z')}",
    ]
    last_detail = "dispatch_failed"
    for attempt in range(1, 7):
        cp = subprocess.run(command, text=True, capture_output=True, check=False)
        if cp.returncode == 0:
            cursor["successor_dispatch_at_utc"] = now.isoformat().replace("+00:00", "Z")
            row["cursor"] = cursor
            row["updated_at"] = now.isoformat().replace("+00:00", "Z")
            return True, "dispatched"

        last_detail = (cp.stderr or cp.stdout or "dispatch_failed").strip()[-500:]
        transient = any(
            marker in last_detail.lower()
            for marker in (
                "rate limit",
                "http 403",
                "http 429",
                "secondary rate",
                "temporar",
                "timeout",
                "timed out",
                "connection reset",
                "502",
                "503",
                "504",
            )
        )
        if not transient:
            return False, last_detail
        if attempt < 6:
            time.sleep(min(5 * attempt * attempt, 60))

    return False, f"bounded transient dispatch retry exhausted: {last_detail}"



def _reconcile_drain_stuck(row: dict, phase: dict, now: datetime) -> bool:
    """Close an interrupted pre-cutoff collection claim during ANALYZE/DRAIN."""
    if (
        phase.get("phase") != "ANALYZE"
        or phase.get("analysis_stage") != "DRAIN"
        or row.get("schema_version") != "alina.resumable_campaign.v2"
        or row.get("creation_phase") != "COLLECT"
        or int(row.get("phase_epoch") or 0) != int(phase.get("source_collection_epoch") or 0)
        or row.get("status") != "STUCK"
        or row.get("stuck_reason") != "LEASE_EXPIRED_REQUIRES_RECONCILIATION"
        or row.get("lease") is not None
    ):
        return False
    cutoff_raw = phase.get("collection_cutoff_at_utc")
    if not cutoff_raw:
        return False
    try:
        cutoff = parse(cutoff_raw)
    except (TypeError, ValueError):
        return False
    previous_lease = None
    for event in reversed(row.get("history") or []):
        if isinstance(event, dict) and event.get("event") == "WATCHDOG_LEASE_EXPIRED":
            candidate = event.get("previous_lease")
            if isinstance(candidate, dict):
                previous_lease = candidate
                break
    acquired = None
    if previous_lease:
        acquired_raw = previous_lease.get("acquired_at") or previous_lease.get("acquired_at_utc")
        if acquired_raw:
            try:
                acquired = parse(acquired_raw)
            except (TypeError, ValueError):
                acquired = None
    completed = row.get("completed_units") if isinstance(row.get("completed_units"), dict) else {}
    if acquired is None:
        terminal_status = "FAILED"
        reason = "DRAIN_MISSING_PRE_CUTOFF_CLAIM_EVIDENCE"
    elif acquired > cutoff:
        terminal_status = "FAILED"
        reason = "DRAIN_CLAIM_STARTED_AFTER_CUTOFF"
    elif completed:
        terminal_status = "PARTIAL"
        reason = "DRAIN_CUTOFF_INTERRUPTED_AFTER_DURABLE_PROGRESS"
    else:
        terminal_status = "UNAVAILABLE"
        reason = "DRAIN_CUTOFF_INTERRUPTED_WITHOUT_DURABLE_PROGRESS"
    campaign_id = str(row.get("campaign_id") or "")
    row["status"] = terminal_status
    row["status_reason"] = reason
    row["stuck_reason"] = None
    row["lease"] = None
    row["updated_at"] = now.isoformat().replace("+00:00", "Z")
    row.setdefault("history", []).append({
        "at_utc": row["updated_at"],
        "event": "WATCHDOG_DRAIN_CUTOFF_TERMINALIZED",
        "previous_status": "STUCK",
        "terminal_status": terminal_status,
        "reason": reason,
        "collection_cutoff_at_utc": cutoff_raw,
        "source_collection_epoch": phase.get("source_collection_epoch"),
    })
    row["terminal_evidence_digest"] = hashlib.sha256(json.dumps({
        "campaign_id": campaign_id,
        "terminal_status": terminal_status,
        "reason": reason,
        "completed_units": completed,
        "collection_cutoff_at_utc": cutoff_raw,
        "source_collection_epoch": phase.get("source_collection_epoch"),
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    return True

def _market_replacement_key(row: dict) -> tuple | None:
    if row.get("kind") != "market_collection":
        return None
    cursor = row.get("cursor") if isinstance(row.get("cursor"), dict) else {}
    phase_epoch = row.get("phase_epoch")
    shard_index = cursor.get("market_shard_index")
    universe_digest = cursor.get("universe_digest")
    plan_sha256 = cursor.get("plan_sha256")
    if (
        not isinstance(phase_epoch, int)
        or shard_index is None
        or not universe_digest
        or not plan_sha256
    ):
        return None
    return (phase_epoch, int(shard_index), str(universe_digest), str(plan_sha256))


def _progressed_market_replacement(row: dict) -> bool:
    status = str(row.get("status") or "")
    if status not in {"RUNNING", "CONTINUATION_REQUIRED", "COMPLETE"}:
        return False
    return bool(
        int(row.get("attempts") or 0) > 0
        or row.get("completed_units")
        or row.get("lease")
    )


def _terminalize_superseded_stuck(
    row: dict, replacement: dict, now: datetime
) -> bool:
    """Preserve a failed campaign as terminal once a newer equivalent shard progresses."""
    if str(row.get("status") or "") != "STUCK":
        return False
    if not _progressed_market_replacement(replacement):
        return False
    key = _market_replacement_key(row)
    if key is None or key != _market_replacement_key(replacement):
        return False
    campaign_id = str(row.get("campaign_id") or "")
    replacement_id = str(replacement.get("campaign_id") or "")
    if not campaign_id or not replacement_id or campaign_id == replacement_id:
        return False
    try:
        old_created = parse(row.get("created_at") or row.get("created_at_utc") or row.get("updated_at"))
        new_created = parse(
            replacement.get("created_at")
            or replacement.get("created_at_utc")
            or replacement.get("updated_at")
        )
    except (TypeError, ValueError):
        return False
    if new_created <= old_created:
        return False

    previous_reason = row.get("status_reason") or row.get("stuck_reason") or "STUCK"
    timestamp = now.isoformat().replace("+00:00", "Z")
    row["status"] = "FAILED"
    row["status_reason"] = "SUPERSEDED_BY_NEWER_MARKET_CAMPAIGN"
    row["stuck_reason"] = None
    row["lease"] = None
    row["updated_at"] = timestamp
    row.setdefault("history", []).append({
        "at_utc": timestamp,
        "event": "WATCHDOG_STUCK_SUPERSEDED",
        "previous_status": "STUCK",
        "previous_reason": previous_reason,
        "replacement_campaign_id": replacement_id,
        "reason": row["status_reason"],
    })
    row["terminal_evidence_digest"] = hashlib.sha256(
        json.dumps(
            {
                "campaign_id": campaign_id,
                "terminal_status": "FAILED",
                "reason": row["status_reason"],
                "previous_reason": previous_reason,
                "replacement_campaign_id": replacement_id,
                "completed_units": row.get("completed_units") or {},
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return True


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--campaign-root", default="catalog/campaigns")
    p.add_argument("--phase-state", default="control/alina-phase.json")
    p.add_argument("--output", default="catalog/CAMPAIGN_WATCHDOG_RECEIPT.json")
    p.add_argument("--dispatch", action="store_true")
    a = p.parse_args()
    now = datetime.now(timezone.utc)
    active = {"PENDING", "RUNNING", "CONTINUATION_REQUIRED", "STUCK"}
    counts = {}
    kind_counts = {}
    backlog_by_kind = {}
    campaign_health = []
    pending_ages_seconds = []
    stalled_pending = []
    next_due_candidates = []
    lease_summary = []
    stuck = []
    expired_leases = []
    unsafe = []
    manifests = sorted(Path(a.campaign_root).glob("*.json"))
    market_replacements = {}
    for candidate_path in manifests:
        try:
            candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if not isinstance(candidate, dict) or not _progressed_market_replacement(candidate):
            continue
        key = _market_replacement_key(candidate)
        if key is None:
            continue
        current = market_replacements.get(key)
        if current is None:
            market_replacements[key] = candidate
            continue
        try:
            candidate_created = parse(
                candidate.get("created_at")
                or candidate.get("created_at_utc")
                or candidate.get("updated_at")
            )
            current_created = parse(
                current.get("created_at")
                or current.get("created_at_utc")
                or current.get("updated_at")
            )
        except (TypeError, ValueError):
            continue
        if candidate_created > current_created:
            market_replacements[key] = candidate
    dispatched = []
    dispatch_failures = []
    lease_repairs = []
    drain_reconciled = []
    phase = {}
    phase_error = None
    try:
        phase = json.loads(Path(a.phase_state).read_text(encoding="utf-8"))
        if (
            not isinstance(phase, dict)
            or phase.get("phase") not in {"IDLE", "COLLECT", "ANALYZE"}
            or not isinstance(phase.get("epoch"), int)
        ):
            raise ValueError("invalid phase state")
    except (OSError, ValueError):
        phase = {}
        phase_error = "invalid_phase_state"
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    for path in manifests:
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            unsafe.append(path.name)
            counts["INVALID_MANIFEST"] = counts.get("INVALID_MANIFEST", 0) + 1
            dispatch_failures.append({
                "campaign_id": path.stem,
                "reason": "invalid_manifest",
                "detail": str(exc)[-300:],
            })
            continue
        if not isinstance(row, dict):
            unsafe.append(path.name)
            counts["INVALID_MANIFEST"] = counts.get("INVALID_MANIFEST", 0) + 1
            dispatch_failures.append({
                "campaign_id": path.stem,
                "reason": "manifest_not_object",
            })
            continue
        status = str(row.get("status") or "")
        kind = str(row.get("kind") or "UNKNOWN")
        if row.get("schema_version") == "alina.resumable_campaign.v1" and status in active:
            campaign_id = str(row.get("campaign_id") or path.stem)
            previous_lease = row.get("lease")
            history = row.setdefault("history", [])
            history.append({
                "at_utc": now.isoformat().replace("+00:00", "Z"),
                "event": "WATCHDOG_LEGACY_V1_TERMINALIZED",
                "previous_status": status,
                "previous_lease": previous_lease,
                "reason": "LEGACY_SCHEMA_HAS_NO_PHASE_EPOCH_AND_CANNOT_RESUME",
            })
            row["lease"] = None
            row["status"] = "FAILED"
            row["status_reason"] = "LEGACY_V1_EXPIRED_EPOCH"
            row["updated_at"] = now.isoformat().replace("+00:00", "Z")
            row["terminal_evidence_digest"] = hashlib.sha256(
                json.dumps(
                    {
                        "campaign_id": campaign_id,
                        "previous_status": status,
                        "reason": row["status_reason"],
                        "completed_units": row.get("completed_units") or {},
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            lease_repairs.append(campaign_id)
            _write_atomic(path, row)
            status = "FAILED"
        if _reconcile_drain_stuck(row, phase, now):
            status = str(row.get("status") or "")
            campaign_id = str(row.get("campaign_id") or path.stem)
            drain_reconciled.append(campaign_id)
            lease_repairs.append(campaign_id)
            _write_atomic(path, row)
        if _reconcile_finished_owner(row, now):
            status = str(row.get("status") or "")
            campaign_id = str(row.get("campaign_id") or path.stem)
            lease_repairs.append(campaign_id)
            _write_atomic(path, row)
        replacement = market_replacements.get(_market_replacement_key(row))
        if (
            phase.get("phase") == "COLLECT"
            and row.get("phase_epoch") == phase.get("epoch")
            and replacement is not None
            and _terminalize_superseded_stuck(row, replacement, now)
        ):
            status = str(row.get("status") or "")
            campaign_id = str(row.get("campaign_id") or path.stem)
            lease_repairs.append(campaign_id)
            _write_atomic(path, row)
        counts[status] = counts.get(status, 0) + 1
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        if status in active:
            backlog_by_kind[kind] = backlog_by_kind.get(kind, 0) + 1
        created_raw = row.get("created_at_utc") or row.get("created_at") or row.get("updated_at")
        created_age = None
        if created_raw:
            try:
                created_age = max(0.0, (now - parse(created_raw)).total_seconds())
                if status == "PENDING":
                    pending_ages_seconds.append(created_age)
            except (TypeError, ValueError):
                created_age = None
        cursor = row.get("cursor") if isinstance(row.get("cursor"), dict) else {}
        due_raw = row.get("next_due_at_utc") or row.get("next_due_at") or cursor.get("next_due_at_utc")
        if due_raw:
            try:
                next_due_candidates.append({"campaign_id": str(row.get("campaign_id") or path.stem), "at_utc": parse(due_raw).isoformat().replace("+00:00", "Z")})
            except (TypeError, ValueError):
                pass
        lease = row.get("lease") if isinstance(row.get("lease"), dict) else None
        if lease:
            lease_summary.append({
                "campaign_id": str(row.get("campaign_id") or path.stem),
                "owner": lease.get("owner") or lease.get("owner_id"),
                "acquired_at_utc": lease.get("acquired_at_utc"),
                "expires_at_utc": lease.get("expires_at") or lease.get("expires_at_utc"),
            })
        if (
            status == "PENDING"
            and created_age is not None
            and created_age > PENDING_CONTROLLER_SLO_SECONDS
            and int(row.get("attempts") or cursor.get("attempts") or 0) == 0
        ):
            stalled_pending.append(str(row.get("campaign_id") or path.stem))
        campaign_health.append({
            "campaign_id": str(row.get("campaign_id") or path.stem),
            "kind": kind,
            "status": status,
            "phase": row.get("creation_phase"),
            "phase_epoch": row.get("phase_epoch"),
            "execution_backend": row.get("execution_backend") or "github-hosted",
            "created_age_seconds": created_age,
            "next_due_at_utc": due_raw,
            "lease": lease,
            "chunk_index": row.get("chunk_index") or cursor.get("chunk_index"),
            "attempts": row.get("attempts") or cursor.get("attempts"),
            "no_progress_count": row.get("no_progress_count"),
            "consecutive_failure_count": row.get("consecutive_failure_count"),
            "last_checkpoint": row.get("checkpoint") or row.get("last_checkpoint"),
            "reason": row.get("stuck_reason") or row.get("blocking_reason") or row.get("reason"),
        })
        if status in active and (
            row.get("paper_only") is not True
            or row.get("read_only") is not True
            or row.get("real_execution") is not False
        ):
            unsafe.append(path.name)
        if status == "STUCK":
            stuck.append(str(row.get("campaign_id") or path.stem))
        if (
            a.dispatch
            and phase.get("phase") == "COLLECT"
            and row.get("creation_phase") == "COLLECT"
            and row.get("phase_epoch") == phase.get("epoch")
            and status == "CONTINUATION_REQUIRED"
            and repository
        ):
            ok, detail = _dispatch_successor(row, repository, now)
            if ok:
                dispatched.append(str(row.get("campaign_id") or path.stem))
                _write_atomic(path, row)
            else:
                dispatch_failures.append({
                    "campaign_id": str(row.get("campaign_id") or path.stem),
                    "reason": detail,
                })
        lease = row.get("lease")
        if isinstance(lease, dict) and lease.get("expires_at"):
            try:
                lease_expired = parse(lease["expires_at"]) <= now
            except (TypeError, ValueError):
                lease_expired = True
            if lease_expired and status in active:
                campaign_id = str(row.get("campaign_id") or path.stem)
                expired_leases.append(campaign_id)
                # Expired ownership must not remain resumable or appear alive to
                # the operator surface. Preserve the evidence, revoke the lease,
                # and force the next worker to reconcile from the last checkpoint.
                history = row.setdefault("history", [])
                history.append({
                    "at_utc": now.isoformat().replace("+00:00", "Z"),
                    "event": "WATCHDOG_LEASE_EXPIRED",
                    "previous_status": status,
                    "previous_lease": dict(lease),
                })
                row["lease"] = None
                row["status"] = "STUCK"
                counts[status] = max(0, counts.get(status, 0) - 1)
                counts["STUCK"] = counts.get("STUCK", 0) + 1
                row["stuck_reason"] = "LEASE_EXPIRED_REQUIRES_RECONCILIATION"
                row["updated_at"] = now.isoformat().replace("+00:00", "Z")
                lease_repairs.append(campaign_id)
                _write_atomic(path, row)
    receipt = {
        "schema": "alina.campaign_watchdog_receipt.v1",
        "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
        "campaign_count": len(manifests),
        "status_counts": dict(sorted(counts.items())),
        "kind_counts": dict(sorted(kind_counts.items())),
        "backlog_by_kind": dict(sorted(backlog_by_kind.items())),
        "oldest_pending_age_seconds": max(pending_ages_seconds) if pending_ages_seconds else None,
        "pending_controller_slo_seconds": PENDING_CONTROLLER_SLO_SECONDS,
        "stalled_pending_campaigns": sorted(stalled_pending),
        "next_due_campaigns": sorted(next_due_candidates, key=lambda item: item["at_utc"]),
        "active_leases": sorted(lease_summary, key=lambda item: item["campaign_id"]),
        "campaign_health": sorted(campaign_health, key=lambda item: item["campaign_id"]),
        "stuck_campaigns": sorted(stuck),
        "expired_leases": sorted(expired_leases),
        "lease_repairs": sorted(set(lease_repairs)),
        "drain_reconciled_campaigns": sorted(set(drain_reconciled)),
        "unsafe_campaigns": sorted(unsafe),
        "successors_dispatched": sorted(dispatched),
        "successor_dispatch_failures": sorted(
            dispatch_failures, key=lambda item: item["campaign_id"]
        ),
        "phase_checked": phase,
        "phase_error": phase_error,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
        "watchdog_status": (
            "BLOCKED"
            if unsafe or phase_error
            else ("ATTENTION" if stuck or expired_leases or dispatch_failures or stalled_pending else "HEALTHY")
        ),
    }
    target = Path(a.output)
    _write_atomic(target, receipt)


if __name__ == "__main__":
    main()
