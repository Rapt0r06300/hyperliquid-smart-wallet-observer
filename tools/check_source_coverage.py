"""Validate a V26 source universe and print its honest current gap state."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from hl_observer.alerts.coverage import (
    SourceCoverageError,
    build_source_coverage_receipt,
    load_source_coverage_universe,
)
from hl_observer.alerts.coverage_completeness import (
    CoverageCompletenessError,
    build_coverage_completeness_attestation,
)
from hl_observer.collection.collecte_fiable import ecrire_atomique

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE = ROOT / "config" / "alerts" / "source_coverage_universe.json"


def _observations(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SourceCoverageError("SOURCE_OBSERVATIONS_FILE_NOT_LIST")
    return payload


def _object(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SourceCoverageError("SOURCE_COVERAGE_INPUT_NOT_OBJECT")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--universe", type=Path, default=DEFAULT_UNIVERSE)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--evaluated-at-ms", type=int)
    parser.add_argument("--allocation", type=Path)
    parser.add_argument("--completeness-evidence", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        inputs = [args.universe, args.observations, args.allocation, args.completeness_evidence]
        if args.output is not None and any(
            path is not None and args.output.resolve() == path.resolve() for path in inputs
        ):
            raise SourceCoverageError("SOURCE_COVERAGE_OUTPUT_OVERWRITES_INPUT")
        evaluated_at_ms = (
            args.evaluated_at_ms
            if args.evaluated_at_ms is not None
            else time.time_ns() // 1_000_000
        )
        universe = load_source_coverage_universe(args.universe)
        receipt = build_source_coverage_receipt(
            universe,
            _observations(args.observations),
            evaluated_at_ms=evaluated_at_ms,
        )
        attestation = build_coverage_completeness_attestation(
            receipt,
            evaluated_at_ms=evaluated_at_ms,
            allocation_percent=_object(args.allocation),
            evidence=_object(args.completeness_evidence),
        )
        if args.output is not None:
            ecrire_atomique(
                args.output,
                json.dumps(
                    {
                        "schema_version": "hypersmart.source_coverage_report.v1",
                        "coverage_receipt": receipt,
                        "completeness_attestation": attestation,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    indent=2,
                ) + "\n",
            )
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        SourceCoverageError,
        CoverageCompletenessError,
    ) as exc:
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
        f"operational={receipt['operational_state']} "
        f"completeness={attestation['coverage_state']} "
        f"receipt={receipt['receipt_hash']} "
        f"attestation={attestation['attestation_hash']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
