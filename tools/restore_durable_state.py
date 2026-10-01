#!/usr/bin/env python3
"""Reconstruct Dataset V2 state on a fresh runner and emit a durable restore receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit(f"invalid timestamp: {value}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", default="catalog/campaigns")
    parser.add_argument("--health", default="catalog/DATASET_HEALTH_RECEIPT.json")
    parser.add_argument("--phase", default="control/alina-phase.json")
    parser.add_argument("--output", default="catalog/DURABLE_RESTORE_RECEIPT.json")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    campaign_root = Path(args.campaign_dir)
    manifests = []
    checkpoint_count = 0
    lease_count = 0
    expired_lease_count = 0
    completed_unit_ids: dict[str, list[str]] = {}
    for path in sorted(campaign_root.glob("*.json")):
        value = json.loads(path.read_text(encoding="utf-8"))
        required = {
            "campaign_id", "kind", "status", "code_sha", "dataset_repo",
            "dataset_generation", "config_sha256", "work_plan_sha256",
        }
        missing = required - set(value)
        if missing:
            raise SystemExit(f"{path}: missing {sorted(missing)}")
        if (
            value.get("paper_only") is not True
            or value.get("read_only") is not True
            or value.get("real_execution") is not False
        ):
            raise SystemExit(f"{path}: unsafe execution identity")
        units = value.get("completed_units") or {}
        if not isinstance(units, dict):
            raise SystemExit(f"{path}: completed_units must be an object")
        ids = sorted(str(unit_id) for unit_id in units)
        completed_unit_ids[str(value["campaign_id"])] = ids
        checkpoint_count += len(ids)
        lease = value.get("lease")
        if isinstance(lease, dict) and lease.get("expires_at"):
            lease_count += 1
            if parse_time(lease["expires_at"]) <= now:
                expired_lease_count += 1
        manifests.append({
            "campaign_id": value["campaign_id"],
            "kind": value["kind"],
            "status": value["status"],
            "phase": value.get("phase"),
            "phase_epoch": value.get("phase_epoch"),
            "source_collection_epoch": value.get("source_collection_epoch"),
            "dataset_selection_id": value.get("dataset_selection_id"),
            "checkpoint_count": len(ids),
            "completed_unit_ids": ids,
        })

    health = json.loads(Path(args.health).read_text(encoding="utf-8"))
    if health.get("schema_version") != "alina.dataset_health_receipt.v1":
        raise SystemExit("unsupported health receipt schema")
    receipt_digest = health.get("receipt_digest")
    body = dict(health)
    body.pop("receipt_digest", None)
    if hashlib.sha256(canonical(body).encode()).hexdigest() != receipt_digest:
        raise SystemExit("health receipt digest mismatch")
    consistency = health.get("phase_consistency") or {}
    if consistency.get("status") == "BLOCKED":
        raise SystemExit("health receipt reports active campaign phase mismatch")

    phase = json.loads(Path(args.phase).read_text(encoding="utf-8"))
    required_phase = {"phase", "epoch", "requested_at_utc", "collection_started_at_utc",
                      "collection_cutoff_at_utc", "source_collection_epoch", "analysis_stage"}
    if required_phase - set(phase):
        raise SystemExit(f"phase state missing {sorted(required_phase - set(phase))}")
    if phase["phase"] not in {"IDLE", "COLLECT", "ANALYZE"}:
        raise SystemExit(f"invalid phase {phase.get('phase')}")
    if not isinstance(phase["epoch"], int) or phase["epoch"] < 1:
        raise SystemExit("invalid phase epoch")

    receipt = {
        "schema": "alina.durable_restore_receipt.v1",
        "generated_at_utc": now.isoformat().replace("+00:00", "Z"),
        "restore_source": "repository durable state",
        "cache_used": False,
        "phase_state": phase,
        "campaign_count": len(manifests),
        "campaigns": manifests,
        "checkpoint_count": checkpoint_count,
        "lease_count": lease_count,
        "expired_lease_count": expired_lease_count,
        "health_receipt_digest": receipt_digest,
        "completed_unit_ids": completed_unit_ids,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    receipt["receipt_digest"] = hashlib.sha256(canonical(receipt).encode()).hexdigest()
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "campaigns": len(manifests),
        "checkpoints": checkpoint_count,
        "health_receipt_digest": receipt_digest,
        "restore_receipt_digest": receipt["receipt_digest"],
        "cache_used": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
