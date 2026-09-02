"""Validate a V26 source universe and print its honest current gap state."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from hl_observer.alerts.coverage import (
    SourceCoverageError,
    build_source_coverage_receipt,
    load_source_coverage_universe,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = ROOT / "config" / "alerts" / "source_coverage_universe.json"


def _observations(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SourceCoverageError("SOURCE_OBSERVATIONS_FILE_NOT_LIST")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--evaluated-at-ms", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        universe = load_source_coverage_universe(args.universe)
        receipt = build_source_coverage_receipt(
            universe,
            _observations(args.observations),
            evaluated_at_ms=args.evaluated_at_ms,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SourceCoverageError) as exc:
        print(f"SOURCE_COVERAGE_INVALID error={exc}")
        return 2
    counts = receipt["counts"]
    print(
        "SOURCE_COVERAGE_OK "
        f"workflow={receipt['workflow_id']} "
        f"classes={counts['classes']} "
        f"desired={counts['desired_sources']} "
        f"connected={counts['actually_connected_sources']} "
        f"blocking_gaps={counts['blocking_gaps']} "
        f"completeness={receipt['completeness_state']} "
        f"receipt={receipt['receipt_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
