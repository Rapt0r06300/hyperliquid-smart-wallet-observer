#!/usr/bin/env python3
"""Build an honest H-T115/H-T170 receipt from a cloud collector summary.

The collector summary is an observation, not a causal proof.  This tool binds
the summary and the selection file to the exact repository HEAD and emits
``UNMEASURABLE`` unless a row-level causal LIVE_WS receipt is supplied by the
collector.  It never invents fills, L4 rows, epochs, or pairing claims.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCHEMA = "hypersmart.copy_vault_live_probe_receipt.v1"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )
    value = result.stdout.strip().lower()
    if result.returncode != 0 or len(value) != 40 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise RuntimeError("EXACT_HEAD_UNAVAILABLE")
    return value


def _nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _digest(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_receipt(
    summary: dict[str, Any],
    *,
    summary_path: Path,
    selection_path: Path | None,
    head_sha: str,
    evidence_kind: str = "safe_replay",
) -> dict[str, Any]:
    if evidence_kind not in {"safe_replay", "l4_capture"}:
        raise ValueError("evidence_kind must be safe_replay or l4_capture")
    missing: list[str] = []
    if summary.get("schema") != "alina.copy_vault_cloud_window.v2":
        missing.append("COLLECTOR_SCHEMA_INVALID")
    run_id = summary.get("collection_run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        missing.append("COLLECTION_RUN_ID_MISSING")
    if summary.get("read_only") is not True:
        missing.append("READ_ONLY_NOT_PROVEN")
    if summary.get("real_execution") is not False:
        missing.append("REAL_EXECUTION_FLAG_INVALID")

    live_counts = summary.get("live_fill_counts")
    if not isinstance(live_counts, dict):
        missing.append("LIVE_FILL_COUNTS_MISSING")
        live_total = None
    else:
        values = list(live_counts.values())
        if any(not _nonnegative_int(value) for value in values):
            missing.append("LIVE_FILL_COUNTS_INVALID")
            live_total = None
        else:
            live_total = sum(values)

    l2 = summary.get("l2_diagnostics")
    l2_frames = summary.get("l2_frames")
    if not _nonnegative_int(l2_frames):
        missing.append("L2_FRAME_COUNT_MISSING")
    if not isinstance(l2, dict):
        missing.append("L2_DIAGNOSTICS_MISSING")

    subscription = summary.get("subscription_diagnostics")
    if not isinstance(subscription, dict):
        missing.append("SUBSCRIPTION_DIAGNOSTICS_MISSING")

    selection_sha = _sha256(selection_path) if selection_path is not None else None
    if selection_path is None:
        missing.append("SELECTION_FILE_MISSING")

    # A cloud summary does not contain row-level ACK/epoch/native identity.
    # Even a positive live_fill_counts value is therefore not causal proof.
    causal_rows = 0
    missing.append("ROW_LEVEL_CAUSAL_LIVE_WS_RECEIPT_MISSING")
    missing.append("L4_POINT_IN_TIME_PAIRING_MISSING")
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": evidence_kind,
        "head_sha": head_sha,
        "collection_run_id": run_id,
        "evidence_status": "UNMEASURABLE",
        "decision": "NO_GO",
        "public_observation": True,
        "read_only": summary.get("read_only") is True,
        # The cloud collector is explicitly PAPER/read-only.  Preserve that
        # fact as ``real_execution=false``; do not invert the source flag.
        "real_execution": summary.get("real_execution") is True,
        "claims": {
            "causal_post_ack_fill_proven": False,
            "l4_fill_l2_pairing_proven": False,
            "websocket_userfills_acknowledged": bool(
                isinstance(subscription, dict)
                and _nonnegative_int(subscription.get("acknowledged"))
                and subscription.get("acknowledged", 0) > 0
            ),
            "l2_observation_received": bool(_nonnegative_int(l2_frames) and l2_frames > 0),
            "snapshot_exclusion_proven": False,
        },
        "observation": {
            "summary_path": str(summary_path),
            "summary_sha256": _sha256(summary_path),
            "selection_path": str(selection_path) if selection_path is not None else None,
            "selection_file_sha256": selection_sha,
            "live_fill_total_reported": live_total,
            "l2_frames_reported": l2_frames if _nonnegative_int(l2_frames) else None,
            "l2_diagnostics": l2 if isinstance(l2, dict) else None,
            "subscription_diagnostics": subscription if isinstance(subscription, dict) else None,
            "causal_row_count": causal_rows,
            "missing_evidence": sorted(set(missing)),
        },
        "next_safe_action": (
            "Run another bounded public read-only window after an active vault emits "
            "a row-level LIVE_WS fill containing ACK time, epoch, native identity, "
            "cutoff and anti-double-count evidence; retain the raw summary and hashes."
        ),
    }
    receipt["receipt_sha256"] = _digest(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--selection-file", type=Path)
    parser.add_argument(
        "--evidence-kind",
        choices=("safe_replay", "l4_capture"),
        default="safe_replay",
        help="Closure-gate role for this observation; it never changes measured data.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        summary = json.loads(args.summary.read_text(encoding="utf-8"))
        if not isinstance(summary, dict):
            raise ValueError("SUMMARY_NOT_OBJECT")
        receipt = build_receipt(
            summary,
            summary_path=args.summary,
            selection_path=args.selection_file,
            head_sha=_git_head(args.repo_root),
            evidence_kind=args.evidence_kind,
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
        "live_fill_total_reported": receipt["observation"]["live_fill_total_reported"],
        "causal_row_count": receipt["observation"]["causal_row_count"],
    }, sort_keys=True))
    return 0 if receipt["evidence_status"] == "PROVEN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
