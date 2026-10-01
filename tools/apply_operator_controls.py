#!/usr/bin/env python3
"""Apply persisted pause/resume intents to the Dataset V2 phase state."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--alina-root", required=True)
    p.add_argument("--phase-path", default="control/alina-phase.json")
    a = p.parse_args()
    root = Path(a.alina_root) / "control" / "operator-intents"
    if not root.is_dir():
        return
    state = json.loads(Path(a.phase_path).read_text(encoding="utf-8"))
    rows = []
    for path in root.glob("*.json"):
        row = json.loads(path.read_text(encoding="utf-8"))
        if str(row.get("intent") or "") in {"pause", "resume", "retry"}:
            rows.append((str(row.get("requested_at_utc") or ""), str(row.get("request_id") or ""), path, row))
    # One control decision is authoritative: the newest immutable intent.
    for _, _, path, row in sorted(rows, reverse=True)[:1]:
        if row.get("paper_only") is not True or row.get("read_only") is not True or row.get("real_execution") is not False:
            raise SystemExit(f"unsafe operator intent: {path}")
        intent = str(row.get("intent") or "")
        if intent not in {"pause", "resume", "retry"}:
            continue
        request_id = str(row.get("request_id") or "")
        if not request_id:
            raise SystemExit(f"missing request id: {path}")
        if state.get("request_id") == request_id:
            continue
        config = row.get("config") if isinstance(row.get("config"), dict) else {}
        if intent == "retry":
            campaign_id = str(config.get("campaign_id") or "")
            target = Path("catalog/campaigns") / (campaign_id + ".json")
            if not campaign_id or not target.is_file():
                raise SystemExit("retry intent requires an existing config.campaign_id")
            command = [
                "python",
                str(Path(a.alina_root) / "tools/resumable_campaign.py"),
                "retry",
                str(target),
                "--reason",
                request_id,
            ]
            result = subprocess.run(command, check=False, capture_output=True, text=True)
            if result.returncode:
                raise SystemExit(result.stderr or result.stdout or "campaign retry failed")
            continue
        target = "IDLE" if intent == "pause" else str(config.get("phase") or config.get("resume_phase") or "COLLECT")
        if target not in {"IDLE", "COLLECT", "ANALYZE"}:
            raise SystemExit(f"invalid resume phase: {target}")
        command = [
            "python",
            "tools/set_phase.py",
            "--phase", target,
            "--request-id", request_id,
            "--requested-by", str(row.get("requested_by") or "operator"),
            "--path", a.phase_path,
        ]
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(result.stderr or result.stdout or "phase control failed")
        state = json.loads(Path(a.phase_path).read_text(encoding="utf-8"))
    print(json.dumps({"phase": state.get("phase"), "epoch": state.get("epoch")}, sort_keys=True))


if __name__ == "__main__":
    main()
