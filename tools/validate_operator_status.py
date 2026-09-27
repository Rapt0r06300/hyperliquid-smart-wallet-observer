#!/usr/bin/env python3
"""Validate the durable operator intent/status contract without executing work."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

TERMINAL = {"COMPLETE", "FAILED", "BLOCKED", "CANCELLED"}
NON_TERMINAL = {"DISPATCHED", "RUNNING"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--intent", required=True)
    parser.add_argument("--status", required=True)
    args = parser.parse_args()
    intent = json.loads(Path(args.intent).read_text(encoding="utf-8"))
    status = json.loads(Path(args.status).read_text(encoding="utf-8"))
    if intent.get("schema_version") != "alina.operator_intent.v1":
        raise SystemExit("OPERATOR_INTENT_SCHEMA_INVALID")
    if status.get("schema_version") != "alina.operator_status.v1":
        raise SystemExit("OPERATOR_STATUS_SCHEMA_INVALID")
    if status.get("request_id") != intent.get("request_id"):
        raise SystemExit("OPERATOR_STATUS_REQUEST_MISMATCH")
    if status.get("intent") != intent.get("intent"):
        raise SystemExit("OPERATOR_STATUS_INTENT_MISMATCH")
    expected_digest = hashlib.sha256(json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if status.get("intent_digest") != expected_digest:
        raise SystemExit("OPERATOR_STATUS_INTENT_DIGEST_MISMATCH")
    if status.get("state") not in NON_TERMINAL | TERMINAL:
        raise SystemExit("OPERATOR_STATUS_STATE_INVALID")
    if status.get("terminal") != (status["state"] in TERMINAL):
        raise SystemExit("OPERATOR_STATUS_TERMINAL_MISMATCH")
    for key, expected in (("paper_only", True), ("read_only", True), ("real_execution", False)):
        if intent.get(key) is not expected or status.get(key) is not expected:
            raise SystemExit("OPERATOR_STATUS_SECURITY_MISMATCH")
    print(json.dumps({
        "request_id": intent["request_id"],
        "state": status["state"],
        "terminal": status["terminal"],
        "valid": True,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
