#!/usr/bin/env python3
"""Validate the canonical dual-repository closure receipt structure."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

REQUIRED = {
    "main_alina_head", "dataset_v2_head", "canonical_spec_blob",
    "phase", "phase_epoch", "source_collection_epoch", "analysis_stage",
    "campaign_ids", "workflow_run_ids", "dataset_selection_id",
    "trade_count_exact", "unique_trade_count_exact", "safe_count",
    "replay_compatible_count", "copy_vault_status", "lead_lag_status",
    "cross_venue_status", "oos_status", "forward_status",
    "two_segment_resume_status", "event_intelligence_wiring_complete",
    "scoreboard_artifact", "paper_read_only", "self_hosted_used",
    "real_execution_reachable", "remaining_blockers",
}
VALID_STATUSES = {"PROVEN", "MORE_DATA", "UNMEASURABLE", "KILL"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="docs/alina-closure-report.json")
    args = parser.parse_args()
    receipt = json.loads(Path(args.path).read_text(encoding="utf-8"))
    if receipt.get("schema_version") != "alina.final_closure_receipt.v1":
        raise SystemExit("unsupported closure receipt schema")
    missing = sorted(REQUIRED - set(receipt))
    if missing:
        raise SystemExit(f"closure receipt missing fields: {missing}")
    supplied = receipt.get("receipt_digest")
    body = dict(receipt)
    body.pop("receipt_digest", None)
    expected = hashlib.sha256(canonical(body).encode()).hexdigest()
    if supplied != expected:
        raise SystemExit("closure receipt digest mismatch")
    if receipt["phase"] not in {"IDLE", "COLLECT", "ANALYZE"}:
        raise SystemExit("invalid closure phase")
    if not isinstance(receipt["phase_epoch"], int) or receipt["phase_epoch"] < 1:
        raise SystemExit("invalid closure phase epoch")
    for name in ("copy_vault_status", "lead_lag_status", "cross_venue_status"):
        if receipt[name] not in VALID_STATUSES:
            raise SystemExit(f"invalid family status: {name}")
    if receipt["paper_read_only"] is not True:
        raise SystemExit("paper/read-only closure invariant missing")
    if receipt["self_hosted_used"] is not False:
        raise SystemExit("self-hosted closure invariant violated")
    if receipt["real_execution_reachable"] is not False:
        raise SystemExit("real execution closure invariant violated")
    if not isinstance(receipt["remaining_blockers"], list):
        raise SystemExit("remaining_blockers must be a list")
    print(json.dumps({
        "schema": receipt["schema_version"],
        "receipt_digest": supplied,
        "remaining_blockers": len(receipt["remaining_blockers"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
