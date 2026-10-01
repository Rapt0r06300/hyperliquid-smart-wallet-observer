#!/usr/bin/env python3
"""Seal unclaimed collection work at the canonical ANALYZE cutoff."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

UNCLAIMED = {"PENDING", "CONTINUATION_REQUIRED", "STUCK"}


def atomic_write(path: Path, row: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(row, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-path", default="control/alina-phase.json")
    parser.add_argument("--campaign-dir", default="catalog/campaigns")
    args = parser.parse_args()
    phase = json.loads(Path(args.phase_path).read_text(encoding="utf-8"))
    if phase.get("phase") != "ANALYZE":
        print(json.dumps({"sealed": 0, "reason": "not_analyze"}))
        return 0
    source_epoch = phase.get("source_collection_epoch")
    cutoff = phase.get("collection_cutoff_at_utc")
    sealed: list[str] = []
    for path in sorted(Path(args.campaign_dir).glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if (
            row.get("creation_phase") != "COLLECT"
            or row.get("phase_epoch") != source_epoch
            or row.get("status") not in UNCLAIMED
            or row.get("lease") is not None
        ):
            continue
        campaign_id = str(row.get("campaign_id") or path.stem)
        row.setdefault("history", []).append(
            {
                "at_utc": cutoff,
                "event": "COLLECTION_CUTOFF_SEALED_UNCLAIMED",
                "previous_status": row.get("status"),
            }
        )
        row["status"] = "UNAVAILABLE"
        row["status_reason"] = "COLLECTION_CUTOFF_BEFORE_CLAIM"
        row["updated_at"] = cutoff
        row["terminal_evidence_digest"] = hashlib.sha256(
            json.dumps(
                {
                    "campaign_id": campaign_id,
                    "source_collection_epoch": source_epoch,
                    "cutoff": cutoff,
                    "completed_units": row.get("completed_units") or {},
                    "reason": row["status_reason"],
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        atomic_write(path, row)
        sealed.append(campaign_id)
    print(json.dumps({"sealed": len(sealed), "campaign_ids": sealed}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
