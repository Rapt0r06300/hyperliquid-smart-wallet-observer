#!/usr/bin/env python3
"""Advance one ANALYZE stage when its canonical durable gate is satisfied."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ORDER = ("DRAIN", "QUALITY", "REPLAY", "BACKTEST", "OOS", "FORWARD_PAPER", "PNL_PROOF", "SCOREBOARD", "DONE")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-path", default="control/alina-phase.json")
    args = parser.parse_args()
    phase_path = Path(args.phase_path)
    state = json.loads(phase_path.read_text(encoding="utf-8"))
    if state.get("phase") != "ANALYZE":
        print(json.dumps({"status": "INERT", "reason": "phase_is_not_analyze"}, sort_keys=True))
        return 0
    current = state.get("analysis_stage")
    if current not in ORDER:
        raise SystemExit("invalid analysis stage")
    if current == "DONE":
        print(json.dumps({"status": "DONE", "stage": current}, sort_keys=True))
        return 0
    target = ORDER[ORDER.index(current) + 1]
    state_digest = hashlib.sha256(
        json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    request_id = hashlib.sha256(
        f"{state['epoch']}:{current}:{target}:{state_digest}".encode("utf-8")
    ).hexdigest()
    completed = subprocess.run(
        [
            sys.executable,
            "tools/advance_analysis_stage.py",
            "--stage",
            target,
            "--request-id",
            request_id,
            "--expected-epoch",
            str(state["epoch"]),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "current_stage": current,
                    "target_stage": target,
                    "reason": (completed.stderr or completed.stdout or "gate_blocked").strip()[-1000:],
                },
                sort_keys=True,
            )
        )
        return 0
    print(
        json.dumps(
            {
                "status": "ADVANCED",
                "previous_stage": current,
                "new_stage": target,
                "request_id": request_id,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
