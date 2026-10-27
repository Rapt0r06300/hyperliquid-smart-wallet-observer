#!/usr/bin/env python3
"""Validate the durable operator intent/status contract without executing work."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from operator_family_contract import normalize_operator_family

TERMINAL = {"COMPLETE", "FAILED", "BLOCKED", "CANCELLED"}
NON_TERMINAL = {"DISPATCHED", "RUNNING"}
CONTROL_INTENTS = {"pause", "resume", "retry"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--intent", required=True)
    parser.add_argument("--status", required=True)
    args = parser.parse_args()
    intent = json.loads(Path(args.intent).read_text(encoding="utf-8"))
    status = json.loads(Path(args.status).read_text(encoding="utf-8"))
    if intent.get("schema_version") not in {"alina.operator_intent.v1", "alina.operator_intent.v2"}:
        raise SystemExit("OPERATOR_INTENT_SCHEMA_INVALID")
    if status.get("schema_version") not in {"alina.operator_status.v1", "alina.operator_status.v2"}:
        raise SystemExit("OPERATOR_STATUS_SCHEMA_INVALID")
    if status.get("request_id") != intent.get("request_id"):
        raise SystemExit("OPERATOR_STATUS_REQUEST_MISMATCH")
    if status.get("intent") != intent.get("intent"):
        raise SystemExit("OPERATOR_STATUS_INTENT_MISMATCH")
    import re
    request_id = intent.get("request_id")
    if not isinstance(request_id, str) or not re.fullmatch(r"[0-9a-f]{64}", request_id):
        raise SystemExit("OPERATOR_STATUS_REQUEST_ID_INVALID")
    if intent.get("schema_version") == "alina.operator_intent.v2":
        if intent.get("phase") not in {"IDLE", "COLLECT", "ANALYZE"}:
            raise SystemExit("OPERATOR_INTENT_PHASE_INVALID")
        if isinstance(intent.get("phase_epoch"), bool) or not isinstance(intent.get("phase_epoch"), int) or intent["phase_epoch"] < 1:
            raise SystemExit("OPERATOR_INTENT_PHASE_EPOCH_INVALID")
        if intent.get("phase") == "ANALYZE" and not intent.get("source_collection_epoch"):
            raise SystemExit("OPERATOR_INTENT_SOURCE_EPOCH_MISSING")
    if intent.get("schema_version") == "alina.operator_intent.v2":
        for key in ("phase", "phase_epoch", "source_collection_epoch", "collection_cutoff_at_utc", "strategy_family"):
            if status.get(key) != intent.get(key):
                raise SystemExit(f"OPERATOR_STATUS_{key.upper()}_MISMATCH")
    try:
        family, _ = normalize_operator_family(
            str(intent.get("intent") or ""),
            intent.get("strategy_family"),
            intent.get("config"),
            scope_root=Path(__file__).resolve().parents[1],
        )
    except ValueError as exc:
        raise SystemExit(f"OPERATOR_INTENT_FAMILY_INVALID:{exc}") from exc
    if (
        intent.get("schema_version") == "alina.operator_intent.v2"
        and intent.get("strategy_family") != family
    ):
        raise SystemExit("OPERATOR_INTENT_FAMILY_MISMATCH")
    expected_digest = hashlib.sha256(json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if status.get("intent_digest") != expected_digest:
        raise SystemExit("OPERATOR_STATUS_INTENT_DIGEST_MISMATCH")
    if status.get("state") not in NON_TERMINAL | TERMINAL:
        raise SystemExit("OPERATOR_STATUS_STATE_INVALID")
    if status.get("terminal") != (status["state"] in TERMINAL):
        raise SystemExit("OPERATOR_STATUS_TERMINAL_MISMATCH")
    supersession_reason = status.get("status_reason") == "SUPERSEDED_BY_NEWER_CONTROL_INTENT"
    superseded_by = status.get("superseded_by_request_id")
    if supersession_reason:
        if (
            intent.get("intent") not in CONTROL_INTENTS
            or status.get("state") != "BLOCKED"
            or status.get("terminal") is not True
            or not isinstance(superseded_by, str)
            or not re.fullmatch(r"[0-9a-f]{64}", superseded_by)
            or superseded_by == request_id
        ):
            raise SystemExit("OPERATOR_STATUS_SUPERSESSION_INVALID")
        replacement_path = Path(args.intent).parent / f"{superseded_by}.json"
        try:
            replacement = json.loads(replacement_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise SystemExit("OPERATOR_STATUS_SUPERSESSION_INVALID") from exc
        replacement_order = (
            str(replacement.get("requested_at_utc") or ""),
            str(replacement.get("request_id") or ""),
        )
        current_order = (
            str(intent.get("requested_at_utc") or ""),
            request_id,
        )
        if (
            replacement.get("schema_version")
            not in {"alina.operator_intent.v1", "alina.operator_intent.v2"}
            or replacement.get("request_id") != superseded_by
            or replacement.get("intent") not in CONTROL_INTENTS
            or replacement.get("paper_only") is not True
            or replacement.get("read_only") is not True
            or replacement.get("real_execution") is not False
            or replacement_order <= current_order
        ):
            raise SystemExit("OPERATOR_STATUS_SUPERSESSION_INVALID")
    elif superseded_by is not None:
        raise SystemExit("OPERATOR_STATUS_SUPERSESSION_INVALID")
    if (
        intent.get("schema_version") == "alina.operator_intent.v2"
        and intent.get("intent") in CONTROL_INTENTS
        and status.get("state") == "COMPLETE"
    ):
        receipt = status.get("control_receipt")
        if (
            not isinstance(receipt, dict)
            or receipt.get("schema_version") != "alina.operator_control_receipt.v1"
            or receipt.get("request_id") != request_id
            or receipt.get("intent") != intent.get("intent")
            or receipt.get("intent_digest") != expected_digest
            or receipt.get("target_identity") in (None, "")
            or not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("evidence_digest") or ""))
            or receipt.get("applied") is not True
            or receipt.get("paper_only") is not True
            or receipt.get("read_only") is not True
            or receipt.get("real_execution") is not False
            or status.get("control_receipt_sha256")
            != hashlib.sha256(
                json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        ):
            raise SystemExit("OPERATOR_CONTROL_RECEIPT_INVALID")
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
