#!/usr/bin/env python3
"""Apply durable operator phase requests through the canonical phase mutator."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

VALID_PHASES = {"IDLE", "COLLECT", "ANALYZE"}
REQUEST_SCHEMAS = {"alina.phase_request.v1", "alina.phase_request.v2"}


def _valid_receipt(row: dict, receipt: object) -> bool:
    if not isinstance(receipt, dict):
        return False
    previous_phase = receipt.get("previous_phase")
    previous_epoch = receipt.get("previous_epoch")
    new_phase = receipt.get("new_phase")
    new_epoch = receipt.get("new_epoch")
    digest = receipt.get("state_digest")
    if (
        receipt.get("schema") != "alina.phase_transition_receipt.v1"
        or receipt.get("request_id") != row.get("request_id")
        or new_phase != row.get("phase")
        or previous_phase not in VALID_PHASES
        or type(previous_epoch) is not int
        or previous_epoch < 1
        or type(new_epoch) is not int
        or new_epoch != previous_epoch + (new_phase != previous_phase)
        or not isinstance(digest, str)
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or not str(receipt.get("transitioned_at_utc") or "").endswith("Z")
        or receipt.get("paper_only") is not True
        or receipt.get("read_only") is not True
        or receipt.get("real_execution") is not False
    ):
        return False
    return row.get("schema") != "alina.phase_request.v2" or (
        previous_phase == row.get("expected_phase")
        and previous_epoch == row.get("expected_epoch")
    )


def _phase_state_matches_receipt(phase_path: Path, row: dict, receipt: dict) -> bool:
    try:
        state = json.loads(phase_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    digest = hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return (
        state.get("phase") == row.get("phase")
        and state.get("epoch") == receipt.get("new_epoch")
        and state.get("request_id") == row.get("request_id")
        and digest == receipt.get("state_digest")
    )


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
        if row.get("schema") not in REQUEST_SCHEMAS:
            raise SystemExit(f"{path}: unsupported request schema")
        if row.get("phase") not in VALID_PHASES:
            raise SystemExit(f"{path}: unsupported phase")
        if row.get("schema") == "alina.phase_request.v2" and (
            row.get("expected_phase") not in VALID_PHASES
            or type(row.get("expected_epoch")) is not int
            or row["expected_epoch"] < 1
        ):
            raise SystemExit(f"{path}: V2 request requires an expected phase and positive epoch")
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
            receipt_data = json.loads(receipt.read_text(encoding="utf-8"))
            if not _valid_receipt(row, receipt_data):
                raise SystemExit(f"{receipt}: phase receipt does not match its immutable request")
            if row["phase"] == "ANALYZE" and _phase_state_matches_receipt(
                Path(args.phase_path), row, receipt_data
            ):
                subprocess.run(
                    [sys.executable, "tools/seal_collection_cutoff.py", "--phase-path", args.phase_path],
                    check=True,
                )
            skipped.append(request_id)
            continue
        if row.get("schema") != "alina.phase_request.v2":
            raise SystemExit(
                f"{path}: historical V1 phase request has no receipt; automatic replay is forbidden"
            )
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
        command.extend(
            [
                "--expected-phase",
                str(row["expected_phase"]),
                "--expected-epoch",
                str(row["expected_epoch"]),
            ]
        )
        subprocess.run(command, check=True)
        if not receipt.is_file() or not _valid_receipt(
            row, json.loads(receipt.read_text(encoding="utf-8"))
        ):
            raise SystemExit(f"{request_id}: phase mutator did not persist a valid receipt")
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
