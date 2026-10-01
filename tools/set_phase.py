#!/usr/bin/env python3
"""Apply one idempotent manual phase transition and persist its receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_identity(value: str, name: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value or ""):
        raise SystemExit(f"invalid {name}")
    return value


def validate_request_id(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", value or ""):
        raise SystemExit("request id must be exactly 64 lowercase hex characters")
    return value


def validate_stamp(value: str) -> str:
    if not value or not str(value).endswith("Z"):
        raise SystemExit("timestamp must be UTC and end in Z")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise SystemExit("invalid UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise SystemExit("timestamp timezone must be UTC")
    return str(value)


def atomic_write(path: Path, payload: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, path)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_receipt(state, *, previous_phase, previous_epoch, request_id, path):
    receipt = {
        "schema": "alina.phase_transition_receipt.v1",
        "request_id": request_id,
        "previous_phase": previous_phase,
        "previous_epoch": previous_epoch,
        "new_phase": state["phase"],
        "new_epoch": state["epoch"],
        "state_digest": digest(state),
        "transitioned_at_utc": state["requested_at_utc"],
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        old = json.loads(target.read_text(encoding="utf-8"))
        stable = dict(receipt)
        stable.pop("transitioned_at_utc", None)
        old_stable = dict(old)
        old_stable.pop("transitioned_at_utc", None)
        if stable != old_stable:
            raise SystemExit("phase receipt identity conflict")
        return
    target.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["IDLE", "COLLECT", "ANALYZE"], required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--requested-by", default="operator")
    parser.add_argument("--cutoff-at-utc")
    parser.add_argument("--path", default="control/alina-phase.json")
    parser.add_argument("--receipt-dir", default="control/phase-receipts")
    args = parser.parse_args()
    args.request_id = validate_request_id(args.request_id)
    args.requested_by = validate_identity(args.requested_by, "requested_by")

    path = Path(args.path)
    state = json.loads(path.read_text(encoding="utf-8"))
    receipt_path = Path(args.receipt_dir) / (args.request_id + ".json")
    if state.get("request_id") == args.request_id and state.get("phase") == args.phase:
        if receipt_path.exists():
            existing = json.loads(receipt_path.read_text(encoding="utf-8"))
            if (
                existing.get("schema") != "alina.phase_transition_receipt.v1"
                or existing.get("request_id") != args.request_id
                or existing.get("new_phase") != state.get("phase")
                or existing.get("new_epoch") != state.get("epoch")
                or existing.get("state_digest") != digest(state)
                or existing.get("paper_only") is not True
                or existing.get("read_only") is not True
                or existing.get("real_execution") is not False
            ):
                raise SystemExit("phase receipt identity conflict")
        else:
            write_receipt(
                state,
                previous_phase=state.get("phase"),
                previous_epoch=state.get("epoch"),
                request_id=args.request_id,
                path=receipt_path,
            )
        print(json.dumps(state, sort_keys=True))
        return 0

    old_phase = state.get("phase")
    old_epoch = state.get("epoch")
    if old_phase not in {"IDLE", "COLLECT", "ANALYZE"} or not isinstance(old_epoch, int) or old_epoch < 1:
        raise SystemExit("invalid current phase state")
    if args.phase == old_phase:
        write_receipt(
            state,
            previous_phase=old_phase,
            previous_epoch=old_epoch,
            request_id=args.request_id,
            path=receipt_path,
        )
        print(json.dumps(state, sort_keys=True))
        return 0
    if args.phase == "ANALYZE" and old_phase != "COLLECT":
        raise SystemExit("ANALYZE requires current COLLECT phase")
    stamp = validate_stamp(args.cutoff_at_utc or now())
    if args.phase == "COLLECT":
        next_state = {
            **state,
            "phase": "COLLECT",
            "epoch": old_epoch + (old_phase != "COLLECT"),
            "requested_at_utc": stamp,
            "collection_started_at_utc": stamp,
            "collection_cutoff_at_utc": None,
            "source_collection_epoch": None,
            "analysis_stage": None,
            "requested_by": args.requested_by,
            "request_id": args.request_id,
        }
    elif args.phase == "ANALYZE":
        next_state = {
            **state,
            "phase": "ANALYZE",
            "epoch": old_epoch + 1,
            "requested_at_utc": stamp,
            "collection_cutoff_at_utc": stamp,
            "source_collection_epoch": old_epoch,
            "analysis_stage": "DRAIN",
            "requested_by": args.requested_by,
            "request_id": args.request_id,
        }
    else:
        next_state = {
            **state,
            "phase": "IDLE",
            "epoch": old_epoch + (old_phase != "IDLE"),
            "requested_at_utc": stamp,
            "collection_started_at_utc": None,
            "collection_cutoff_at_utc": None,
            "source_collection_epoch": None,
            "analysis_stage": None,
            "requested_by": args.requested_by,
            "request_id": args.request_id,
        }
    path.write_text(json.dumps(next_state, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    write_receipt(
        next_state,
        previous_phase=old_phase,
        previous_epoch=old_epoch,
        request_id=args.request_id,
        path=receipt_path,
    )
    print(json.dumps(next_state, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
