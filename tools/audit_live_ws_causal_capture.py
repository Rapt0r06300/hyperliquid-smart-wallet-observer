#!/usr/bin/env python3
"""Audit raw LIVE_WS fills for the canonical H-T170 causal receipt.

This is a read-only transformer: it never adds ACKs, epochs, identities, or
fills.  A capture is PROVEN only when those fields are present in the rows
themselves and all anti-double-count checks pass.  Missing or malformed data
returns exit code 2 and a NOT_PROVEN receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

# Keep direct CLI execution independent from the caller's PYTHONPATH.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hl_observer.backtesting.copy_vault_closure_gate import (
    PROVEN,
    validate_live_ws_causal_receipt,
)

SCHEMA = "hypersmart.copy_vault_live_ws_causal_receipt.v1"


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _receipt_digest(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _git_head_sha() -> str | None:
    """Return the exact repository HEAD, never a guessed or fallback SHA."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[1],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip().lower()
    if result.returncode != 0 or len(value) != 40:
        return None
    if any(char not in "0123456789abcdef" for char in value):
        return None
    return value


def _source_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit(path: Path) -> dict[str, Any]:
    source_sha256 = _source_sha256(path)
    git_sha = _git_head_sha()
    rows: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            parse_errors.append(f"line {line_number}: JSON_INVALID:{exc.msg}")
            continue
        if not isinstance(value, dict):
            parse_errors.append(f"line {line_number}: ROW_NOT_OBJECT")
            continue
        rows.append(value)

    eligible: list[dict[str, Any]] = []
    missing: set[str] = set(parse_errors)
    for index, row in enumerate(rows, 1):
        row_invalid = False
        if row.get("source") != "LIVE_WS":
            missing.add(f"ROW_{index}:LIVE_WS_PROVENANCE_MISSING")
            row_invalid = True
        if row.get("isSnapshot") is not False:
            missing.add(f"ROW_{index}:SNAPSHOT_OR_UNKNOWN_NOT_FORWARD_ELIGIBLE")
            row_invalid = True
            continue
        for field in ("ack_received_at_ms", "capture_epoch", "received_at_ms", "stable_event_id"):
            value = row.get(field)
            if field.endswith("_at_ms"):
                valid = _positive_int(value)
            else:
                valid = isinstance(value, str) and bool(value.strip())
            if not valid:
                missing.add(f"ROW_{index}:{field.upper()}_MISSING")
                row_invalid = True
        ack = row.get("ack_received_at_ms")
        received = row.get("received_at_ms")
        if _positive_int(ack) and _positive_int(received) and received < ack:
            missing.add(f"ROW_{index}:RECEIVED_BEFORE_ACK")
            row_invalid = True
        if row.get("post_ack") is not True:
            missing.add(f"ROW_{index}:POST_ACK_NOT_PROVEN")
            row_invalid = True
        if not all(row.get(field) not in (None, "") for field in ("ts_ms", "coin", "tid")):
            missing.add(f"ROW_{index}:NATIVE_IDENTITY_INCOMPLETE")
            row_invalid = True
        if not row_invalid:
            eligible.append(row)

    stable_ids = [row.get("stable_event_id") for row in eligible]
    native_ids = [
        (row.get("ts_ms"), row.get("coin"), row.get("tid")) for row in eligible
    ]
    stable_unique = len(stable_ids) == len(set(stable_ids))
    native_unique = len(native_ids) == len(set(native_ids))
    if eligible and not stable_unique:
        missing.add("STABLE_EVENT_ID_DUPLICATE")
    if eligible and not native_unique:
        missing.add("NATIVE_IDENTITY_DUPLICATE")

    epochs = sorted({str(row.get("capture_epoch")) for row in eligible if row.get("capture_epoch")})
    claims = {
        "causal_live_fill_rows": len(eligible),
        "post_ack": bool(eligible) and all(row.get("post_ack") is True for row in eligible),
        "cutoff_epoch_present": bool(epochs),
        "anti_double_count": bool(eligible) and stable_unique and native_unique,
        "native_identity_reconciled": bool(eligible) and all(
            all(row.get(field) not in (None, "") for field in ("ts_ms", "coin", "tid"))
            for row in eligible
        ),
        "snapshot_excluded_from_forward": bool(eligible) and all(
            row.get("isSnapshot") is False for row in eligible
        ),
        "live_ws_provenance": bool(eligible) and all(
            row.get("source") == "LIVE_WS" for row in eligible
        ),
    }
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "git_sha": git_sha,
        "completed": not missing and bool(eligible),
        "paper_read_only": True,
        "real_execution": False,
        "claims": claims,
        "capture": {
            "source_path": str(path),
            "source_sha256": source_sha256,
            "row_count": len(rows),
            "causal_row_count": len(eligible),
            "capture_epochs": epochs,
            "missing_evidence": sorted(missing),
        },
    }
    receipt["receipt_sha256"] = _receipt_digest(receipt)
    receipt["validation"] = validate_live_ws_causal_receipt(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fills", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = audit(args.fills)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 1
    print(json.dumps({
        "output": str(args.output),
        "status": receipt["validation"]["status"],
        "causal_row_count": receipt["capture"]["causal_row_count"],
        "missing_evidence_count": len(receipt["capture"]["missing_evidence"]),
    }, sort_keys=True))
    return 0 if receipt["validation"]["status"] == PROVEN else 2


if __name__ == "__main__":
    raise SystemExit(main())
