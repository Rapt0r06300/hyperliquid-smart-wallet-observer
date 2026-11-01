#!/usr/bin/env python3
"""Rebind the available Kronos freeze observation to the exact local HEAD.

This is a provenance transformer only.  It never turns model metadata into a
training cutoff, dependency lock, preregistered protocol, or economic result.
Those fields remain explicitly missing until an authoritative source exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any


SCHEMA = "hypersmart.copy_vault.kronos_freeze_receipt.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _head_sha(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=False,
        capture_output=True, text=True, timeout=5,
    )
    value = result.stdout.strip().lower()
    if result.returncode != 0 or len(value) != 40 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise RuntimeError("EXACT_HEAD_UNAVAILABLE")
    return value


def _digest(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_receipt(source: dict[str, Any], *, source_path: Path, head_sha: str) -> dict[str, Any]:
    rows = source if isinstance(source, list) else [source]
    observed = rows[0] if rows and isinstance(rows[0], dict) else {}
    original_claims = observed.get("claims") if isinstance(observed.get("claims"), dict) else {}
    unresolved = observed.get("claims", {}).get("unresolved", []) if isinstance(observed.get("claims"), dict) else []
    missing = sorted({
        "DEPENDENCY_HASH_LOCK_MISSING",
        "AUTHORITATIVE_POST_TRAINING_CUTOFF_MISSING",
        "PREREGISTERED_PROTOCOL_MISSING",
        "MEASURED_TRAIN_OOS_FORWARD_REPORT_MISSING",
        "EXACT_HEAD_REBOUND_FROM_HISTORICAL_RECEIPT",
        *[str(item) for item in unresolved],
    })
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "head_sha": head_sha,
        "evidence_status": "UNMEASURABLE",
        "decision": "NO_GO",
        "paper_read_only": True,
        "real_execution": False,
        "source": {
            "path": str(source_path),
            "sha256": _sha256(source_path),
            "historical_head_sha": observed.get("head_sha"),
            "historical_source": observed.get("source"),
        },
        "observed_claims": original_claims,
        "claims": {
            "repo_model_tokenizer_license_frozen": original_claims.get("repo_model_tokenizer_license_frozen") is True,
            "dependency_hashes": False,
            "cutoff_frozen": False,
            "protocol_preregistered": False,
            "post_training_cutoff": False,
            "sample_count_mean_verified": False,
            "missing_fields_not_zeroed": original_claims.get("missing_fields_not_zeroed") is True,
        },
        "missing_evidence": missing,
        "next_safe_action": (
            "Obtain an authoritative post-training cutoff, a complete hash-locked "
            "dependency manifest, a preregistered protocol, and measured retained "
            "TRAIN/OOS/FORWARD observations before any closure decision."
        ),
    }
    receipt["receipt_sha256"] = _digest(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        source = json.loads(args.source.read_text(encoding="utf-8"))
        receipt = build_receipt(
            source, source_path=args.source, head_sha=_head_sha(args.repo_root)
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 1
    print(json.dumps({
        "output": str(args.output),
        "status": receipt["evidence_status"],
        "decision": receipt["decision"],
        "head_sha": receipt["head_sha"],
        "missing_evidence_count": len(receipt["missing_evidence"]),
    }, sort_keys=True))
    return 0 if receipt["evidence_status"] == "PROVEN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
