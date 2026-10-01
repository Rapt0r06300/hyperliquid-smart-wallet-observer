#!/usr/bin/env python3
"""Apply durable operator phase requests through the canonical phase mutator."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

VALID_PHASES = {"IDLE", "COLLECT", "ANALYZE"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request-dir", default="control/phase-requests")
    parser.add_argument("--receipt-dir", default="control/phase-receipts")
    parser.add_argument("--phase-path", default="control/alina-phase.json")
    args = parser.parse_args()

    request_dir = Path(args.request_dir)
    receipt_dir = Path(args.receipt_dir)
    applied: list[str] = []
    skipped: list[str] = []
    rows: list[tuple[str, Path, dict]] = []

    for path in sorted(request_dir.glob("*.json")):
        row = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(row, dict):
            raise SystemExit(f"{path}: request must be an object")
        request_id = str(row.get("request_id") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", request_id) or path.stem != request_id:
            raise SystemExit(f"{path}: request identity mismatch")
        if row.get("schema") != "alina.phase_request.v1":
            raise SystemExit(f"{path}: unsupported request schema")
        if row.get("phase") not in VALID_PHASES:
            raise SystemExit(f"{path}: unsupported phase")
        if (
            row.get("paper_only") is not True
            or row.get("read_only") is not True
            or row.get("real_execution") is not False
        ):
            raise SystemExit(f"{path}: unsafe request identity")
        requested_at = str(row.get("requested_at_utc") or "")
        if not requested_at.endswith("Z"):
            raise SystemExit(f"{path}: requested_at_utc must be UTC")
        rows.append((requested_at, path, row))

    for _, path, row in sorted(rows, key=lambda item: (item[0], item[1].name)):
        request_id = str(row["request_id"])
        receipt = receipt_dir / f"{request_id}.json"
        if receipt.is_file():
            if row["phase"] == "ANALYZE":
                subprocess.run(
                    [sys.executable, "tools/seal_collection_cutoff.py", "--phase-path", args.phase_path],
                    check=True,
                )
            skipped.append(request_id)
            continue
        command = [
            sys.executable,
            "tools/set_phase.py",
            "--phase",
            str(row["phase"]),
            "--request-id",
            request_id,
            "--requested-by",
            str(row.get("requested_by") or "operator"),
            "--path",
            args.phase_path,
            "--receipt-dir",
            args.receipt_dir,
        ]
        subprocess.run(command, check=True)
        if row["phase"] == "ANALYZE":
            subprocess.run(
                [sys.executable, "tools/seal_collection_cutoff.py", "--phase-path", args.phase_path],
                check=True,
            )
        applied.append(request_id)

    print(json.dumps({"applied": applied, "skipped": skipped}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
