#!/usr/bin/env python3
"""Apply persisted pause/resume/retry intents exactly once and record evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hl_observer.control_plane.resumable_campaign import (
    ANALYZE_CAMPAIGN_KINDS,
    SCHEMA_VERSION_V2,
    CampaignManifest,
    require_campaign_economic_scope,
    sha256_json,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write_json(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        dir=path.parent, prefix=path.name + ".", suffix=".tmp", text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(row, sort_keys=True, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_status(intent: dict[str, Any]) -> tuple[Path, dict[str, Any], bool]:
    request_id = str(intent.get("request_id") or "")
    status_path = Path("control/operator-status") / f"{request_id}.json"
    if not status_path.is_file():
        raise SystemExit(f"operator status missing for request {request_id}")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    digest = hashlib.sha256(
        json.dumps(intent, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    if (
        status.get("schema_version")
        not in {"alina.operator_status.v1", "alina.operator_status.v2"}
        or status.get("request_id") != request_id
        or status.get("intent") != intent.get("intent")
        or status.get("intent_digest") != digest
    ):
        raise SystemExit(f"operator status identity mismatch for request {request_id}")
    for key, expected in (("paper_only", True), ("read_only", True), ("real_execution", False)):
        if intent.get(key) is not expected or status.get(key) is not expected:
            raise SystemExit("operator control is not PAPER / READ-ONLY")
    if intent.get("schema_version") == "alina.operator_intent.v2":
        for key in (
            "phase",
            "phase_epoch",
            "source_collection_epoch",
            "collection_cutoff_at_utc",
            "strategy_family",
        ):
            if status.get(key) != intent.get(key):
                raise SystemExit(f"operator status {key} differs from immutable intent")

    terminal_states = {"COMPLETE", "FAILED", "BLOCKED", "CANCELLED"}
    non_terminal_states = {"DISPATCHED", "RUNNING"}
    state = status.get("state")
    if state not in terminal_states | non_terminal_states:
        raise SystemExit(f"operator control has invalid status state {state}")
    if status.get("terminal") is not (state in terminal_states):
        raise SystemExit("operator control status terminal flag is inconsistent")

    if state == "COMPLETE":
        receipt = status.get("control_receipt")
        if (
            not isinstance(receipt, dict)
            or receipt.get("schema_version") != "alina.operator_control_receipt.v1"
            or receipt.get("request_id") != request_id
            or receipt.get("intent_digest") != digest
            or receipt.get("intent") != intent.get("intent")
            or receipt.get("applied") is not True
            or status.get("control_receipt_sha256") != sha256_json(receipt)
        ):
            raise SystemExit("completed control status lacks matching durable receipt")
        return status_path, status, True
    if state in terminal_states:
        return status_path, status, True
    return status_path, status, False


def _complete_status(
    status_path: Path,
    status: dict[str, Any],
    intent: dict[str, Any],
    *,
    target_identity: str,
    evidence_digest: str,
) -> None:
    intent_digest = status["intent_digest"]
    receipt = {
        "schema_version": "alina.operator_control_receipt.v1",
        "request_id": intent["request_id"],
        "intent": intent["intent"],
        "intent_digest": intent_digest,
        "target_identity": target_identity,
        "evidence_digest": evidence_digest,
        "applied": True,
        "applied_at_utc": _now(),
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    updated = {
        **status,
        "state": "COMPLETE",
        "terminal": True,
        "control_receipt": receipt,
        "control_receipt_sha256": sha256_json(receipt),
        "updated_at_utc": receipt["applied_at_utc"],
    }
    _atomic_write_json(status_path, updated)


def _run(command: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True, env=env)


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    source_root = str(Path(__file__).resolve().parents[1] / "src")
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(value for value in (source_root, existing) if value)
    return env


def _apply_phase_control(
    *,
    intent_path: Path,
    intent: dict[str, Any],
    config: dict[str, Any],
    phase_path: Path,
    env: dict[str, str],
) -> tuple[str, str]:
    action = str(intent.get("intent") or "")
    target_phase = "IDLE" if action == "pause" else str(
        config.get("phase") or config.get("resume_phase") or "COLLECT"
    )
    if target_phase not in {"IDLE", "COLLECT", "ANALYZE"}:
        raise SystemExit(f"invalid phase requested by {action}: {target_phase}")

    current = json.loads(phase_path.read_text(encoding="utf-8"))
    request_id = str(intent["request_id"])
    receipt_path = Path("control/phase-receipts") / f"{request_id}.json"
    if receipt_path.is_file():
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (
            receipt.get("schema") == "alina.phase_transition_receipt.v1"
            and receipt.get("request_id") == request_id
            and receipt.get("new_phase") == target_phase
            and isinstance(receipt.get("state_digest"), str)
            and re.fullmatch(r"[0-9a-f]{64}", receipt["state_digest"])
            and receipt.get("paper_only") is True
            and receipt.get("read_only") is True
            and receipt.get("real_execution") is False
        ):
            return target_phase, sha256_json(receipt)
        raise SystemExit("phase transition receipt identity mismatch")

    source_phase = intent.get("phase")
    source_epoch = intent.get("phase_epoch")
    already_committed = (
        current.get("request_id") == request_id
        and current.get("phase") == target_phase
        and isinstance(source_epoch, int)
        and current.get("epoch") == source_epoch + (target_phase != source_phase)
    )
    if not already_committed and (
        current.get("phase") != source_phase or current.get("epoch") != source_epoch
    ):
        raise SystemExit("phase control intent is stale against the canonical phase epoch")

    command = [
        sys.executable,
        str(Path(__file__).resolve().parent / "set_phase.py"),
        "--phase",
        target_phase,
        "--request-id",
        request_id,
        "--requested-by",
        str(intent.get("requested_by") or "operator"),
        "--expected-phase",
        str(source_phase),
        "--expected-epoch",
        str(source_epoch),
        "--path",
        str(phase_path),
    ]
    result = _run(command, env=env)
    if result.returncode:
        raise SystemExit(result.stderr or result.stdout or "phase control failed")

    updated = json.loads(phase_path.read_text(encoding="utf-8"))
    if updated.get("phase") != target_phase:
        raise SystemExit("phase control did not reach the requested phase")
    if updated.get("request_id") != request_id and current.get("phase") != target_phase:
        raise SystemExit("phase state does not acknowledge the request identity")
    if not receipt_path.is_file():
        raise SystemExit("phase transition receipt was not persisted")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if (
        receipt.get("request_id") != request_id
        or receipt.get("new_phase") != target_phase
        or receipt.get("paper_only") is not True
        or receipt.get("read_only") is not True
        or receipt.get("real_execution") is not False
    ):
        raise SystemExit("phase transition receipt identity mismatch")
    return target_phase, sha256_json(receipt)


def _apply_retry(
    *,
    intent: dict[str, Any],
    config: dict[str, Any],
    alina_root: Path,
    env: dict[str, str],
) -> tuple[str, str]:
    campaign_id = str(config.get("campaign_id") or "")
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", campaign_id)
        or ".." in campaign_id
    ):
        raise SystemExit("retry intent requires a path-safe campaign_id")
    target = Path("catalog/campaigns") / f"{campaign_id}.json"
    campaign_dir = Path("catalog/campaigns").resolve()
    if target.resolve().parent != campaign_dir or not target.is_file():
        raise SystemExit("retry intent requires an existing canonical campaign manifest")
    raw = json.loads(target.read_text(encoding="utf-8"))
    try:
        manifest = CampaignManifest.from_dict(raw)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"retry target manifest invalid: {exc}") from exc
    if (
        manifest.campaign_id != campaign_id
        or manifest.schema_version != SCHEMA_VERSION_V2
        or manifest.creation_phase != "ANALYZE"
        or manifest.kind not in ANALYZE_CAMPAIGN_KINDS
    ):
        raise SystemExit("retry target is not a V2 ANALYZE campaign")
    require_campaign_economic_scope(manifest)

    already_applied = any(
        item.get("from") == "STUCK"
        and item.get("to") == "RUNNING"
        and item.get("reason") == intent["request_id"]
        for item in manifest.history
    )
    if already_applied and manifest.status == "RUNNING":
        evidence = sha256_json(
            {
                "campaign_id": campaign_id,
                "request_id": intent["request_id"],
                "manifest": sha256_json(raw),
            }
        )
        return campaign_id, evidence
    if manifest.status != "STUCK":
        raise SystemExit("retry target is not STUCK and has no matching retry receipt")
    for key in (
        "phase",
        "phase_epoch",
        "source_collection_epoch",
        "collection_cutoff_at_utc",
        "analysis_stage",
    ):
        manifest_key = "creation_phase" if key == "phase" else key
        if getattr(manifest, manifest_key) != intent.get(key):
            raise SystemExit(f"retry target {manifest_key} differs from immutable intent")

    script = alina_root / "tools" / "resumable_campaign.py"
    command = [
        sys.executable,
        str(script),
        "retry",
        str(target),
        "--reason",
        str(intent["request_id"]),
        "--expected-digest",
        sha256_json(raw),
    ]
    result = _run(command, env=env)
    if result.returncode:
        raise SystemExit(result.stderr or result.stdout or "campaign retry failed")

    updated_raw = json.loads(target.read_text(encoding="utf-8"))
    updated = CampaignManifest.from_dict(updated_raw)
    acknowledged = any(
        item.get("from") == "STUCK"
        and item.get("to") == "RUNNING"
        and item.get("reason") == intent["request_id"]
        for item in updated.history
    )
    if updated.status != "RUNNING" or not acknowledged:
        raise SystemExit("campaign manifest does not durably acknowledge retry")
    evidence = sha256_json(
        {
            "campaign_id": campaign_id,
            "request_id": intent["request_id"],
            "manifest": sha256_json(updated_raw),
        }
    )
    return campaign_id, evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--alina-root", required=True)
    parser.add_argument("--phase-path", default="control/alina-phase.json")
    args = parser.parse_args()
    intents_root = Path(args.alina_root) / "control" / "operator-intents"
    if not intents_root.is_dir():
        return 0
    phase_path = Path(args.phase_path)
    phase = json.loads(phase_path.read_text(encoding="utf-8"))
    rows = []
    for intent_path in intents_root.glob("*.json"):
        row = json.loads(intent_path.read_text(encoding="utf-8"))
        if str(row.get("intent") or "") in {"pause", "resume", "retry"}:
            rows.append(
                (
                    str(row.get("requested_at_utc") or ""),
                    str(row.get("request_id") or ""),
                    intent_path,
                    row,
                )
            )

    env = _subprocess_env()
    ordered_rows = sorted(rows, reverse=True)
    selected_rows = ordered_rows[:1]
    last_control_request_id = selected_rows[0][1] if selected_rows else None
    for _, _, intent_path, intent in selected_rows:
        if (
            intent.get("paper_only") is not True
            or intent.get("read_only") is not True
            or intent.get("real_execution") is not False
        ):
            raise SystemExit(f"unsafe operator intent: {intent_path}")
        request_id = str(intent.get("request_id") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", request_id):
            raise SystemExit(f"invalid request id: {intent_path}")
        status_path, status, already_terminal = _load_status(intent)
        if not already_terminal:
            config = intent.get("config") if isinstance(intent.get("config"), dict) else {}
            if intent["intent"] == "retry":
                target_identity, evidence_digest = _apply_retry(
                    intent=intent,
                    config=config,
                    alina_root=Path(args.alina_root),
                    env=env,
                )
            else:
                target_identity, evidence_digest = _apply_phase_control(
                    intent_path=intent_path,
                    intent=intent,
                    config=config,
                    phase_path=phase_path,
                    env=env,
                )
            _complete_status(
                status_path,
                status,
                intent,
                target_identity=target_identity,
                evidence_digest=evidence_digest,
            )
            phase = json.loads(phase_path.read_text(encoding="utf-8"))

    superseded_request_ids = []
    authoritative_request_id = last_control_request_id
    if authoritative_request_id is not None:
        for _, request_id, intent_path, intent in ordered_rows[1:]:
            if (
                intent.get("paper_only") is not True
                or intent.get("read_only") is not True
                or intent.get("real_execution") is not False
            ):
                raise SystemExit(f"unsafe operator intent: {intent_path}")
            status_path, status, already_terminal = _load_status(intent)
            if already_terminal:
                continue
            _atomic_write_json(
                status_path,
                {
                    **status,
                    "state": "BLOCKED",
                    "terminal": True,
                    "status_reason": "SUPERSEDED_BY_NEWER_CONTROL_INTENT",
                    "superseded_by_request_id": authoritative_request_id,
                    "updated_at_utc": _now(),
                },
            )
            superseded_request_ids.append(request_id)
        phase = json.loads(phase_path.read_text(encoding="utf-8"))

    print(
        json.dumps(
            {
                "phase": phase.get("phase"),
                "epoch": phase.get("epoch"),
                "last_control_request_id": last_control_request_id,
                "superseded_control_request_ids": superseded_request_ids,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
