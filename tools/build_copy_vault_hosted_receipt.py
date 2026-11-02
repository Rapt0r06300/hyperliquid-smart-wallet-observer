#!/usr/bin/env python3
"""Build one exact-SHA hosted CI receipt without mutating Agiflow or SAFE data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hl_observer.backtesting.copy_vault_hosted_receipt import (  # noqa: E402
    build_hosted_ci_receipt,
)


def _artifact(artifact_id: str, name: str, digest: str) -> dict[str, str]:
    return {"id": artifact_id, "name": name, "digest": digest}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--workflow", required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-attempt", required=True)
    parser.add_argument("--status", required=True)
    parser.add_argument("--conclusion", required=True)
    parser.add_argument("--pytest-exit-code", required=True, type=int)
    parser.add_argument("--junit-artifact-id", required=True)
    parser.add_argument("--junit-artifact-name", required=True)
    parser.add_argument("--junit-artifact-digest", required=True)
    parser.add_argument("--closure-artifact-id", required=True)
    parser.add_argument("--closure-artifact-name", required=True)
    parser.add_argument("--closure-artifact-digest", required=True)
    parser.add_argument("--tasklist-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        tasklist_report = json.loads(args.tasklist_report.read_text(encoding="utf-8"))
        receipt = build_hosted_ci_receipt(
            repository=args.repository,
            workflow=args.workflow,
            event=args.event,
            ref=args.ref,
            head_sha=args.head_sha,
            run_id=args.run_id,
            run_attempt=args.run_attempt,
            status=args.status,
            conclusion=args.conclusion,
            pytest_exit_code=args.pytest_exit_code,
            junit_artifact=_artifact(
                args.junit_artifact_id,
                args.junit_artifact_name,
                args.junit_artifact_digest,
            ),
            closure_artifact=_artifact(
                args.closure_artifact_id,
                args.closure_artifact_name,
                args.closure_artifact_digest,
            ),
            tasklist_report=tasklist_report,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
