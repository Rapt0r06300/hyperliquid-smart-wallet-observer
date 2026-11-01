#!/usr/bin/env python3
"""Audit all ten Copy-Vault closure plans from supplied receipts only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hl_observer.backtesting.copy_vault_task_closure_plans import (  # noqa: E402
    TASK_IDS,
    evaluate_tasklist,
)


def _read_receipts(directory: Path) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for task_id in TASK_IDS:
        path = directory / f"{task_id}.json"
        if not path.is_file():
            result[task_id] = []
            continue
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, list):
            raise ValueError(f"{path} must contain a JSON array of actual receipts")
        if not all(isinstance(item, dict) for item in value):
            raise ValueError(f"{path} contains a non-object receipt")
        result[task_id] = value
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
