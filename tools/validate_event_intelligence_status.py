#!/usr/bin/env python3
"""Fail-closed validator for the canonical Event Intelligence 1..120 registry."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

STATUSES = {
    "IMPLEMENTED_AND_WIRED",
    "IMPLEMENTED_BUT_PARTIAL",
    "IMPLEMENTED_BUT_NOT_WIRED",
    "BROKEN",
    "MISSING",
    "NOT_APPLICABLE",
}
PROOFS = {"PROVEN", "UNPROVEN", "UNMEASURABLE", "KILL", "MORE_DATA"}
COVERAGE_STATES = {"REGISTERED", "WIRED", "DATA_PRESENT", "CONSUMED", "VALIDATED", "UNMEASURABLE", "UNSUPPORTED", "RETIRED", "NOT_APPLICABLE"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", default="docs/event-intelligence-120-status.json")
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    root = Path(args.repo_root)
    body = json.loads(Path(args.path).read_text(encoding="utf-8"))
    if body.get("schema_version") not in {"alina.event_intelligence_status.v1", "alina.event_intelligence_status.v2"}:
        raise SystemExit("unsupported event registry schema")
    rows = body.get("items")
    if not isinstance(rows, list) or [row.get("id") for row in rows] != list(range(1, 121)):
        raise SystemExit("event registry must contain exactly ids 1..120")
    for row in rows:
        status = row.get("status")
        proof = row.get("proof_status")
        if status not in STATUSES or proof not in PROOFS:
            raise SystemExit(f"invalid state for event {row.get('id')}")
        if row.get("coverage_state") not in COVERAGE_STATES:
            raise SystemExit(f"invalid coverage lifecycle for event {row.get('id')}")
        if row.get("wiring_status") != status:
            raise SystemExit(f"wiring status mismatch for event {row.get('id')}")
        if row.get("required_dataset_family") != "external_events":
            raise SystemExit(f"dataset family missing for event {row.get('id')}")
        target_families = row.get("target_economic_families")
        if target_families != ["copy_vault", "lead_lag", "cross_venue_dislocation"]:
            raise SystemExit(f"target family contract missing for event {row.get('id')}")
        for field in ("actual_callers", "tests", "runtime_evidence"):
            if not isinstance(row.get(field), list):
                raise SystemExit(f"{field} must be a list for event {row.get('id')}")
        files = row.get("evidence_files") or []
        if not isinstance(files, list):
            raise SystemExit(f"invalid evidence list for event {row.get('id')}")
        missing = [item for item in files if not (root / str(item)).is_file()]
        if missing:
            raise SystemExit(f"event {row.get('id')} references missing evidence: {missing}")
        if status == "IMPLEMENTED_AND_WIRED" and not files:
            raise SystemExit(f"event {row.get('id')} claims wired without evidence")
        if proof == "PROVEN" and status != "IMPLEMENTED_AND_WIRED":
            raise SystemExit(f"event {row.get('id')} claims proof without wired implementation")
        component_contract = str(row.get("component_contract") or "")
        callers = row.get("actual_callers") or []
        expected = hashlib.sha256(
            json.dumps(
                {
                    "files": sorted(files),
                    "component_contract": component_contract,
                    "callers": sorted(callers),
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        if row.get("evidence_digest") != expected:
            raise SystemExit(f"event {row.get('id')} evidence digest mismatch")
    summary = body.get("summary") or {}
    for status in STATUSES:
        if int(summary.get(status, 0)) != sum(row["status"] == status for row in rows):
            raise SystemExit(f"summary mismatch for {status}")
    print(json.dumps({"events": len(rows), "registry_digest": body.get("registry_digest")}, sort_keys=True))


if __name__ == "__main__":
    main()
