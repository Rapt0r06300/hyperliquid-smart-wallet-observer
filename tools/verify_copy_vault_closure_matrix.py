#!/usr/bin/env python3
"""Verify a Copy-Vault exact-SHA evidence matrix without mutating Agiflow.

The input files are deliberately explicit JSON: criteria must be copied from
the authoritative Agiflow task and evidence must contain the receipts actually
obtained.  Exit code 0 means every criterion is proven; exit code 2 means the
matrix is valid but still incomplete; exit code 1 means the input is invalid.
No network, GitHub write, task update, or data download is performed here.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hl_observer.backtesting.copy_vault_closure_gate import (
    ClosureCriterion,
    EvidenceRecord,
    build_closure_matrix,
)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc


def _criteria(value: Any) -> list[ClosureCriterion]:
    if not isinstance(value, list):
        raise ValueError("criteria JSON must be a list")
    result: list[ClosureCriterion] = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("criterion must be an object")
        kinds = row.get("required_kinds")
        claims = row.get("required_claims", {})
        if not isinstance(kinds, list) or not all(isinstance(kind, str) for kind in kinds):
            raise ValueError("criterion required_kinds must be a list of strings")
        if not isinstance(claims, dict):
            raise ValueError("criterion required_claims must be an object")
        result.append(
            ClosureCriterion(
                criterion_id=str(row.get("criterion_id") or ""),
                required_kinds=tuple(kinds),
                required_claims=claims,
                require_hosted=row.get("require_hosted") is True,
                require_full_dataset=row.get("require_full_dataset") is True,
                min_distinct_runs=int(row.get("min_distinct_runs", 1)),
                unavailable_is_unmeasurable=(
                    row.get("unavailable_is_unmeasurable") is True
                ),
            )
        )
    return result


def _evidence(value: Any) -> list[EvidenceRecord]:
    if not isinstance(value, list):
        raise ValueError("evidence JSON must be a list")
    if not all(isinstance(row, dict) for row in value):
        raise ValueError("evidence entries must be objects")
    return [EvidenceRecord.from_mapping(row) for row in value]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--criteria", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = build_closure_matrix(
            args.task_id,
            _criteria(_read_json(args.criteria)),
            _evidence(_read_json(args.evidence)),
            expected_head_sha=args.head_sha,
        )
    except (TypeError, ValueError) as exc:
        parser.error(str(exc))
        return 1
    encoded = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output is not None:
        args.output.write_text(encoded, encoding="utf-8", newline="\n")
    else:
        print(encoded, end="")
    return 0 if report["closure_allowed"] is True else 2


if __name__ == "__main__":
    raise SystemExit(main())
