#!/usr/bin/env python3
"""Bind an unavailable external proof gap to the current exact repository HEAD.

This tool is deliberately conservative.  It does not turn a historical run,
an absent hosted run, or an old PR head into evidence.  It creates an explicit
``UNMEASURABLE/NO_GO`` receipt so the closure audit can distinguish an exact
current-head gap from a stale observation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "hypersmart.copy_vault_external_gap_receipt.v1"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def build_external_gap_receipt(
    *,
    task_id: str,
    criterion_id: str,
    evidence_kind: str,
    expected_head_sha: str,
    source: str,
    missing_evidence: list[str],
    historical_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a truthful exact-head gap receipt.

    ``historical_observation`` is retained only as a labelled observation;
    none of its claims are promoted to the current HEAD.  Empty gaps are
    rejected because an explicit unresolved reason is mandatory.
    """
    if not isinstance(task_id, str) or not task_id.startswith("H-T"):
        raise ValueError("task_id must be an H-T task identifier")
    if not isinstance(criterion_id, str) or not criterion_id:
        raise ValueError("criterion_id is required")
    if not isinstance(evidence_kind, str) or not evidence_kind:
        raise ValueError("evidence_kind is required")
    if (
        not isinstance(expected_head_sha, str)
        or len(expected_head_sha) != 40
        or any(char not in "0123456789abcdef" for char in expected_head_sha)
    ):
        raise ValueError("expected_head_sha must be a lowercase 40-character SHA")
    if not isinstance(source, str) or not source:
        raise ValueError("source is required")
    if not isinstance(missing_evidence, list) or not missing_evidence or not all(
        isinstance(item, str) and item for item in missing_evidence
    ):
        raise ValueError("missing_evidence must contain at least one non-empty reason")
    if historical_observation is not None and not isinstance(historical_observation, dict):
        raise ValueError("historical_observation must be an object")

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "task_id": task_id,
        "criterion_id": criterion_id,
        "kind": evidence_kind,
        "source": source,
        "head_sha": expected_head_sha,
        "evidence_status": "UNMEASURABLE",
        "decision": "NO_GO",
        "paper_read_only": True,
        "real_execution": False,
        "full_dataset_certified": False,
        "closure_allowed": False,
        "claims": {},
        "missing_evidence": list(missing_evidence),
        "no_synthetic_substitution": True,
    }
    if historical_observation is not None:
        historical_bytes = _canonical(historical_observation)
        payload["historical_observation"] = {
            "retained_for_traceability_only": True,
            "head_sha": historical_observation.get("head_sha"),
            "run_id": historical_observation.get("run_id"),
            "artifact_id": historical_observation.get("artifact_id"),
            "observation_sha256": _sha256(historical_bytes),
        }
    payload["receipt_sha256"] = _sha256(_canonical(payload))
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--criterion-id", required=True)
    parser.add_argument("--evidence-kind", required=True)
    parser.add_argument("--head-sha", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--missing", action="append", required=True)
    parser.add_argument("--historical", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        historical = None
        if args.historical is not None:
            historical = json.loads(args.historical.read_text(encoding="utf-8"))
            if isinstance(historical, list):
                if len(historical) != 1 or not isinstance(historical[0], dict):
                    raise ValueError("historical JSON list must contain one object")
                historical = historical[0]
        receipt = build_external_gap_receipt(
            task_id=args.task_id,
            criterion_id=args.criterion_id,
            evidence_kind=args.evidence_kind,
            expected_head_sha=args.head_sha,
            source=args.source,
            missing_evidence=args.missing,
            historical_observation=historical,
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
