#!/usr/bin/env python3
"""Build an exact-SHA hosted checkpoint/resume evidence receipt.

The input is the unmodified JSON receipt emitted by the hosted collector soak.
This adapter only binds that observation to the GitHub run and artifact
metadata supplied by the operator.  It never turns a bounded deterministic
soak into a full-dataset, economic, L4, or LIVE_WS claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "hypersmart.copy_vault_hosted_soak_receipt.v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _head_sha(repo_root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    value = result.stdout.strip().lower()
    if result.returncode != 0 or not _SHA_RE.fullmatch(value):
        raise RuntimeError("EXACT_HEAD_UNAVAILABLE")
    return value


def _receipt_digest(payload: dict[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "receipt_sha256"}
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_receipt(
    soak: dict[str, Any],
    *,
    soak_path: Path,
    head_sha: str,
    run_id: str,
    artifact_id: str,
    artifact_digest: str,
    full_dataset_certified: bool = False,
) -> dict[str, Any]:
    if not _SHA_RE.fullmatch(head_sha):
        raise ValueError("head_sha must be a full lowercase commit SHA")
    if not run_id.isdigit():
        raise ValueError("run_id must be numeric")
    if not artifact_id.isdigit():
        raise ValueError("artifact_id must be numeric")
    if not _DIGEST_RE.fullmatch(artifact_digest.lower()):
        raise ValueError("artifact_digest must be sha256:<64 hex characters>")

    resumed = soak.get("resumed") if isinstance(soak.get("resumed"), dict) else {}
    interrupted = soak.get("interrupted") if isinstance(soak.get("interrupted"), dict) else {}
    continuous = soak.get("continuous") if isinstance(soak.get("continuous"), dict) else {}
    same_input = interrupted.get("input_sha256") == resumed.get("input_sha256") == continuous.get("input_sha256")
    same_output = resumed.get("accepted_sha256") == continuous.get("accepted_sha256")
    completed = soak.get("status") == "PASS" and soak.get("same_result_after_resume") is True
    claims = {
        "checkpoint_resume_proven": completed,
        "interruption_state_equivalent": completed and same_input,
        "receipts_equivalent": completed and same_output,
        "incomplete_artifacts_rejected": (
            interrupted.get("status") == "CONTINUATION_REQUIRED"
            and interrupted.get("interrupted") is True
        ),
        "input_count_preserved": (
            interrupted.get("input_count") == resumed.get("input_count") == continuous.get("input_count")
        ),
        "accepted_count_preserved": resumed.get("accepted_count") == continuous.get("accepted_count"),
        "paper_read_only": soak.get("paper_read_only") is True,
        "real_execution": soak.get("real_execution") is False,
    }
    status = "VERIFIED" if completed and all(claims.values()) else "UNMEASURABLE"
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": "github_hosted",
        "evidence_status": status,
        "decision": "GO" if status == "VERIFIED" else "NO_GO",
        "head_sha": head_sha,
        "run_id": run_id,
        "artifact_id": artifact_id,
        "artifact_sha256": artifact_digest.lower().removeprefix("sha256:"),
        "run_status": "completed",
        "conclusion": "success" if completed else "failure",
        "paper_read_only": soak.get("paper_read_only") is True,
        "real_execution": soak.get("real_execution") is False,
        "full_dataset_certified": bool(full_dataset_certified),
        "source": {
            "path": str(soak_path),
            "sha256": _sha256(soak_path),
        },
        "observed": {
            "status": soak.get("status"),
            "same_result_after_resume": soak.get("same_result_after_resume"),
            "interrupted": interrupted,
            "resumed": resumed,
            "continuous": continuous,
            "metrics": {
                "duration_ms": soak.get("duration_ms"),
                "peak_memory_bytes": soak.get("peak_memory_bytes"),
            },
        },
        "claims": claims,
        "missing_evidence": sorted(
            key for key, value in claims.items() if value is not True
        ),
        "next_safe_action": (
            "Run a second distinct exact-SHA hosted receipt for the two-run criterion; "
            "do not use this bounded soak as proof of full SAFE dataset conservation "
            "or economic performance."
        ),
    }
    payload["receipt_sha256"] = _receipt_digest(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--soak", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--artifact-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--full-dataset-certified", action="store_true")
    args = parser.parse_args()
    try:
        soak = json.loads(args.soak.read_text(encoding="utf-8"))
        if not isinstance(soak, dict):
            raise ValueError("soak receipt must be an object")
        receipt = build_receipt(
            soak,
            soak_path=args.soak,
            head_sha=_head_sha(args.repo_root),
            run_id=args.run_id,
            artifact_id=args.artifact_id,
            artifact_digest=args.artifact_digest,
            full_dataset_certified=args.full_dataset_certified,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 1
    print(json.dumps({
        "output": str(args.output),
        "status": receipt["evidence_status"],
        "decision": receipt["decision"],
        "head_sha": receipt["head_sha"],
        "run_id": receipt["run_id"],
        "artifact_id": receipt["artifact_id"],
    }, sort_keys=True))
    return 0 if receipt["evidence_status"] == "VERIFIED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
