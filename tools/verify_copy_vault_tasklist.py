#!/usr/bin/env python3
"""Audit all ten Copy-Vault closure plans from supplied receipts only."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hl_observer.backtesting.copy_vault_task_closure_plans import (  # noqa: E402
    TASK_IDS,
    evaluate_tasklist,
)


def _read_receipts(directory: Path) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for task_id in TASK_IDS:
        # Keep the canonical aggregate while also ingesting append-only
        # exact-SHA receipts emitted as ``H-T95-<evidence>-<sha>.json``.
        # The evaluator remains fail-closed: unusable, stale, or mismatched
        # receipts are still rejected downstream rather than treated as proof.
        canonical = directory / f"{task_id}.json"
        paths = ([canonical] if canonical.is_file() else []) + sorted(
            path for path in directory.glob(f"{task_id}-*.json")
        )
        if not paths:
            result[task_id] = []
            continue
        receipts: list[dict[str, Any]] = []
        for path in paths:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                value = [value]
            if not isinstance(value, list):
                raise ValueError(f"{path} must contain a JSON object or array of actual receipts")
            if not all(isinstance(item, dict) for item in value):
                raise ValueError(f"{path} contains a non-object receipt")
            receipts.extend(value)
        result[task_id] = receipts
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = evaluate_tasklist(
            _read_receipts(args.evidence_dir), expected_head_sha=args.head_sha,
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 1
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf-8", newline="\n")
    else:
        print(encoded, end="")
    return 0 if report["global"]["closure_allowed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
