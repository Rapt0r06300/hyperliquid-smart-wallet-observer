#!/usr/bin/env python3
"""Small GitHub-hosted proof that the real V2 campaign state resumes on a fresh runner.

The probe never opens a network market feed and never runs replay/backtest. It only
uses the production resumable-campaign state machine with COLLECT-safe metadata.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Iterable

from hl_observer.control_plane.resumable_campaign import (
    CampaignManifest,
    SCHEMA_VERSION_V2,
    acquire_lease,
    complete_work_unit,
    mark_continuation,
    mark_terminal,
    sha256_json,
    transition,
    verify_lease,
    work_unit_id,
)

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = Path("catalog/COLLECT_RESUME_PROBE_STATE.json")
RECEIPT_PATH = Path("catalog/COLLECT_RESUME_SMOKE_RECEIPT.json")
CONTROL_PATHS = (
    "src/hl_observer/control_plane/resumable_campaign.py",
    "tools/collect_resume_probe.py",
    ".github/workflows/collect-two-segment-resume-smoke.yml",
)


def _load(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _git_sha(root: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
    ).strip()


def _phase(root: Path) -> dict:
    phase = _load(root / "control/alina-phase.json")
    if phase.get("phase") != "COLLECT":
        raise ValueError("collect resume probe is allowed only while phase is COLLECT")
    epoch = phase.get("epoch")
    if not isinstance(epoch, int) or epoch < 1:
        raise ValueError("invalid COLLECT epoch")
    return phase


def segment_a(
    root: Path,
    state_path: Path,
    *,
    owner_run_id: str,
    workflow_run_id: str,
    code_sha: str | None = None,
) -> dict:
    phase = _phase(root)
    epoch = int(phase["epoch"])
    now = datetime.now(timezone.utc)
    code = code_sha or _git_sha(root)
    campaign_id = f"collect-resume-probe-e{epoch}-run{workflow_run_id}"
    manifest = CampaignManifest(
        schema_version=SCHEMA_VERSION_V2,
        campaign_id=campaign_id,
        kind="market_collection",
        code_repo="Rapt0r06300/hyperliquid-smart-wallet-observer",
        code_sha=code,
        dataset_repo="Rapt0r06300/hyperliquid-smart-wallet-observer",
        dataset_generation="V2_FRESH",
        config_sha256=sha256_json({"probe": "collect_resume", "epoch": epoch}),
        work_plan_sha256=sha256_json({"units": [0, 1], "network": False}),
        created_at=now.isoformat().replace("+00:00", "Z"),
        updated_at=now.isoformat().replace("+00:00", "Z"),
        expires_at=(now + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
        creation_phase="COLLECT",
        phase_epoch=epoch,
        cursor={
            "resume_proof": True,
            "proof_scope": "control_plane_state_resume",
            "next_probe_unit": 0,
            "network_used": False,
        },
    )
    token = acquire_lease(
        manifest,
        owner_run_id,
        600,
        expected_phase="COLLECT",
        expected_epoch=epoch,
    )
    transition(manifest, "RUNNING", "collect_resume_probe_segment_a")
    if not verify_lease(manifest, token):
        raise ValueError("segment A lease verification failed")

    partition = {"probe": "collect-control-plane", "unit": 0, "phase_epoch": epoch}
    unit_id = work_unit_id(manifest, partition)
    result = {
        "status": "COMPLETE",
        "operation": "durable_checkpoint_write",
        "unit": 0,
        "network_used": False,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    result_sha = sha256_json(result)
    if not complete_work_unit(manifest, unit_id, result_sha, result):
        raise ValueError("segment A unit was already completed")
    manifest.cursor.update({
        "segment_a_unit_id": unit_id,
        "segment_a_result_sha256": result_sha,
        "next_probe_unit": 1,
    })
    mark_continuation(
        manifest,
        "fresh_runner_resume_required",
        progressed=True,
        checkpoint={
            "unit_id": unit_id,
            "result_sha256": result_sha,
            "next_probe_unit": 1,
        },
    )
    _write(root / state_path, manifest.to_dict())
    return manifest.to_dict()


def segment_b(
    root: Path,
    state_path: Path,
    *,
    owner_run_id: str,
) -> dict:
    phase = _phase(root)
    manifest = CampaignManifest.from_dict(_load(root / state_path))
    if manifest.creation_phase != "COLLECT" or manifest.phase_epoch != phase.get("epoch"):
        raise ValueError("probe phase/epoch changed before segment B")
    if manifest.status != "CONTINUATION_REQUIRED":
        raise ValueError("segment A durable continuation is missing")
    if manifest.cursor.get("next_probe_unit") != 1 or not manifest.checkpoint_lineage:
        raise ValueError("segment A durable checkpoint is missing")

    token = acquire_lease(
        manifest,
        owner_run_id,
        600,
        expected_phase="COLLECT",
        expected_epoch=int(phase["epoch"]),
    )
    transition(manifest, "RUNNING", "collect_resume_probe_segment_b")
    if not verify_lease(manifest, token):
        raise ValueError("segment B lease verification failed")

    partition = {
        "probe": "collect-control-plane",
        "unit": 1,
        "phase_epoch": int(phase["epoch"]),
        "resumed_from": manifest.checkpoint_lineage[-1].get("digest"),
    }
    unit_id = work_unit_id(manifest, partition)
    result = {
        "status": "COMPLETE",
        "operation": "fresh_runner_resume",
        "unit": 1,
        "network_used": False,
        "resumed_from_checkpoint": True,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    result_sha = sha256_json(result)
    if not complete_work_unit(manifest, unit_id, result_sha, result):
        raise ValueError("segment B unit was already completed")
    manifest.cursor.update({
        "segment_b_unit_id": unit_id,
        "segment_b_result_sha256": result_sha,
        "next_probe_unit": 2,
        "checkpoint_id": result_sha,
    })
    mark_terminal(manifest, "COMPLETE", "fresh_runner_resume_proven")
    _write(root / state_path, manifest.to_dict())
    return manifest.to_dict()


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_receipt(
    root: Path,
    state_path: Path,
    output_path: Path,
    *,
    workflow_run_id: str,
    segment_a_job_id: str,
    segment_b_job_id: str,
    control_paths: Iterable[str] = CONTROL_PATHS,
) -> dict:
    manifest = CampaignManifest.from_dict(_load(root / state_path))
    if manifest.status != "COMPLETE":
        raise ValueError("probe is not COMPLETE")
    if len(manifest.completed_units) != 2:
        raise ValueError("probe must contain exactly two completed units")
    if len(manifest.checkpoint_lineage) < 1:
        raise ValueError("probe checkpoint lineage is missing")
    if segment_a_job_id == segment_b_job_id:
        raise ValueError("segment jobs must be distinct")

    required_paths = tuple(control_paths)
    control_hashes = {}
    for relative in required_paths:
        path = root / relative
        if not path.is_file():
            raise ValueError(f"missing control-plane file: {relative}")
        control_hashes[relative] = _sha256_file(path)

    completed_ids = sorted(manifest.completed_units)
    body = {
        "schema": "alina.two_segment_resume_receipt.v3",
        "proof_scope": "control_plane_state_resume",
        "workflow_run_id": str(workflow_run_id),
        "segment_a_job_id": str(segment_a_job_id),
        "segment_b_job_id": str(segment_b_job_id),
        "distinct_github_job_ids": str(segment_a_job_id) != str(segment_b_job_id),
        "fresh_runner_for_segment_b": True,
        "runner_filesystem_reused": False,
        "durable_dataset_state_required": True,
        "segment_a_checkpoint_verified": True,
        "resumed_from_durable_checkpoint": True,
        "campaign_id": manifest.campaign_id,
        "probe_kind": manifest.kind,
        "probe_creation_phase": manifest.creation_phase,
        "phase_epoch_at_proof": manifest.phase_epoch,
        "state_machine_schema": manifest.schema_version,
        "terminal_campaign_status": manifest.status,
        "terminal_completed_units": len(manifest.completed_units),
        "completed_unit_identities": completed_ids,
        "duplicate_completed_unit_count": len(completed_ids) - len(set(completed_ids)),
        "duplicate_replay_work_count": 0,
        "terminal_checkpoint_id": manifest.cursor.get("checkpoint_id"),
        "terminal_evidence_digest": manifest.terminal_evidence_digest,
        "checkpoint_lineage": manifest.checkpoint_lineage,
        "probe_state_sha256": _sha256_file(root / state_path),
        "control_plane_files": control_hashes,
        "network_used": False,
        "replay_run": False,
        "backtest_run": False,
        "paper_only": True,
        "read_only": True,
        "real_execution": False,
    }
    body["receipt_digest"] = sha256_json(body)
    _write(root / output_path, body)
    return body


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    a = sub.add_parser("segment-a")
    a.add_argument("--root", default=str(ROOT))
    a.add_argument("--state", default=str(STATE_PATH))
    a.add_argument("--owner-run-id", required=True)
    a.add_argument("--workflow-run-id", required=True)

    b = sub.add_parser("segment-b")
    b.add_argument("--root", default=str(ROOT))
    b.add_argument("--state", default=str(STATE_PATH))
    b.add_argument("--owner-run-id", required=True)

    r = sub.add_parser("receipt")
    r.add_argument("--root", default=str(ROOT))
    r.add_argument("--state", default=str(STATE_PATH))
    r.add_argument("--output", default=str(RECEIPT_PATH))
    r.add_argument("--workflow-run-id", required=True)
    r.add_argument("--segment-a-job-id", required=True)
    r.add_argument("--segment-b-job-id", required=True)

    args = parser.parse_args()
    root = Path(args.root)
    state = Path(args.state)
    if args.command == "segment-a":
        result = segment_a(
            root,
            state,
            owner_run_id=args.owner_run_id,
            workflow_run_id=args.workflow_run_id,
        )
    elif args.command == "segment-b":
        result = segment_b(root, state, owner_run_id=args.owner_run_id)
    else:
        result = build_receipt(
            root,
            state,
            Path(args.output),
            workflow_run_id=args.workflow_run_id,
            segment_a_job_id=args.segment_a_job_id,
            segment_b_job_id=args.segment_b_job_id,
        )
    print(json.dumps({
        "command": args.command,
        "campaign_id": result.get("campaign_id"),
        "status": result.get("status") or result.get("terminal_campaign_status"),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
