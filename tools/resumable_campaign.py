#!/usr/bin/env python3
"""Atomic CLI for Dataset V2 campaign manifests."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile

from hl_observer.control_plane.resumable_campaign import (
    CampaignManifest,
    acquire_lease,
    complete_work_unit,
    mark_continuation,
    mark_terminal,
    select_due_campaigns,
    sha256_json,
    transition,
    validate_manifest,
    verify_lease,
)


def load(path: str | Path) -> CampaignManifest:
    return CampaignManifest.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def save(path: str | Path, manifest: CampaignManifest, expected: str | None = None) -> None:
    target = Path(path)
    if target.exists() and expected:
        current = sha256_json(json.loads(target.read_text(encoding="utf-8")))
        if current != expected:
            raise SystemExit("manifest changed")
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(manifest.to_dict(), sort_keys=True, indent=2) + "\n"
    fd, temporary = tempfile.mkstemp(dir=target.parent, prefix=target.name + ".")
    try:
        os.write(fd, data.encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(temporary, target)


def _json_object(raw: str | None) -> dict:
    if not raw:
        return {}
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise SystemExit("cursor-json must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "create",
            "validate",
            "list-due",
            "start",
            "acquire-lease",
            "record-unit",
            "continue",
            "finish",
            "fail",
        ],
    )
    parser.add_argument("path")
    parser.add_argument("--campaign-id")
    parser.add_argument("--kind")
    parser.add_argument("--code-sha")
    parser.add_argument("--dataset-generation", default="V2_FRESH")
    parser.add_argument("--config-sha256", default="schedule")
    parser.add_argument("--work-plan-sha256", default="schedule")
    parser.add_argument("--cursor-json")
    parser.add_argument("--token")
    parser.add_argument("--owner")
    parser.add_argument("--ttl-s", type=int, default=20_700)
    parser.add_argument("--unit-id")
    parser.add_argument("--sha256")
    parser.add_argument("--expected-digest")
    parser.add_argument("--reason", default="cli")
    args = parser.parse_args()
    path = Path(args.path)

    if args.command == "create":
        if path.exists():
            print(sha256_json(json.loads(path.read_text(encoding="utf-8"))))
            return 0
        now = datetime.now(timezone.utc)
        manifest = CampaignManifest(
            args.campaign_id or path.stem,
            args.kind or "",
            "Rapt0r06300/hyperliquid-smart-wallet-observer",
            args.code_sha or "",
            "Rapt0r06300/alina-smartflow-datasets-v2",
            args.dataset_generation,
            args.config_sha256,
            args.work_plan_sha256,
            (now + timedelta(days=7)).isoformat(),
            created_at=now.isoformat(),
            cursor=_json_object(args.cursor_json),
        )
        save(path, manifest)
        print(sha256_json(manifest.to_dict()))
        return 0

    if args.command == "list-due":
        manifests = [load(item) for item in sorted(path.glob("*.json"))]
        print("\n".join(item.campaign_id for item in select_due_campaigns(manifests)))
        return 0

    manifest = load(path)
    if args.command == "validate":
        validate_manifest(manifest)
        print(sha256_json(manifest.to_dict()))
        return 0

    if args.command in {"start", "acquire-lease"}:
        token = acquire_lease(manifest, args.owner or "manual", max(60, int(args.ttl_s)))
        if args.command == "start" and manifest.status != "RUNNING":
            transition(manifest, "RUNNING", "worker_started")
        save(path, manifest, args.expected_digest)
        print(f"::add-mask::{token}")
        print(f"lease_token={token}")
        return 0

    if args.token and not verify_lease(manifest, args.token):
        raise SystemExit("stale lease")

    if args.command == "record-unit":
        complete_work_unit(manifest, args.unit_id or "", args.sha256 or "", {})
        save(path, manifest, args.expected_digest)
        return 0
    if args.command == "continue":
        mark_continuation(manifest, args.reason, progressed=True)
        save(path, manifest, args.expected_digest)
        return 0
    if args.command == "finish":
        mark_terminal(manifest, "COMPLETE", args.reason)
        save(path, manifest, args.expected_digest)
        return 0
    if args.command == "fail":
        mark_terminal(manifest, "FAILED", args.reason)
        save(path, manifest, args.expected_digest)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
