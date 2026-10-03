#!/usr/bin/env python3
"""Supersede active legacy Copy-Vault fan-out campaigns with bounded lanes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ACTIVE = {"PENDING", "RUNNING", "CONTINUATION_REQUIRED", "STUCK"}


def atomic_write(path: Path, row: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(row, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--campaign-dir", default="catalog/campaigns")
    parser.add_argument("--phase-path", default="control/alina-phase.json")
    parser.add_argument("--legacy-version", default="-v6")
    parser.add_argument(
        "--preserve-running",
        action="store_true",
        help="Do not supersede a currently RUNNING lane; let it finish cleanly.",
    )
    args = parser.parse_args()

    phase = json.loads(Path(args.phase_path).read_text(encoding="utf-8"))
    if phase.get("phase") != "COLLECT" or not isinstance(phase.get("epoch"), int):
        print(json.dumps({"superseded": 0, "reason": "not_collect"}))
        return 0

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    superseded: list[str] = []
    for path in sorted(Path(args.campaign_dir).glob("copy-vault-*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if (
            row.get("kind") != "copy_vault_collection"
            or row.get("status") not in ACTIVE
            or row.get("phase_epoch") != phase["epoch"]
            or args.legacy_version not in str(row.get("campaign_id") or path.stem)
        ):
            continue
        campaign_id = str(row.get("campaign_id") or path.stem)
        previous_status = str(row.get("status"))
        if args.preserve_running and previous_status == "RUNNING":
            continue
        row.setdefault("history", []).append(
            {
                "at_utc": now,
                "event": "SUPERSEDED_BY_BOUNDED_COPY_VAULT_LANES",
                "previous_status": previous_status,
                "previous_lease": row.get("lease"),
            }
        )
        row["lease"] = None
        row["status"] = "FAILED"
        row["status_reason"] = "SUPERSEDED_BY_BOUNDED_V7_LANES"
        row["updated_at"] = now
        row["terminal_evidence_digest"] = hashlib.sha256(
            json.dumps(
                {
                    "campaign_id": campaign_id,
                    "phase_epoch": phase["epoch"],
                    "reason": row["status_reason"],
                    "completed_units": row.get("completed_units") or {},
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        atomic_write(path, row)
        superseded.append(campaign_id)

    print(json.dumps({"superseded": len(superseded), "campaign_ids": superseded}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
