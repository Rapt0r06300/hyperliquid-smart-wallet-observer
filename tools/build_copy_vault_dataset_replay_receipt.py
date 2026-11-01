#!/usr/bin/env python3
"""Bind a canonical dataset campaign to the current HEAD without upgrading it.

The dataset campaign is useful evidence even when it is not a closure proof.
This adapter records the exact corpus, campaign result and missing held-out
requirements.  It never turns TRAIN-only output into OOS/FORWARD evidence and
never substitutes a synthetic ablation for the real Copy-Vault observations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

SCHEMA = "hypersmart.copy_vault.dataset_replay_receipt.v1"
TASKS = {"H-T99", "H-T119", "H-T223"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _head_sha(root: Path) -> str:
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


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _segment(result: dict[str, Any], name: str) -> dict[str, Any] | None:
    value = result.get(name)
    return value if isinstance(value, dict) else None


def build_receipt(
    campaign: dict[str, Any],
    provenance: dict[str, Any],
    *,
    task_scope: str,
    head_sha: str,
    campaign_path: Path,
    provenance_path: Path,
) -> dict[str, Any]:
    if task_scope not in TASKS:
        raise ValueError(f"unsupported task scope: {task_scope}")
    if len(head_sha) != 40 or any(char not in "0123456789abcdef" for char in head_sha):
        raise ValueError("head_sha must be a lowercase 40-character SHA")

    oos = _segment(campaign, "oos")
    forward = _segment(campaign, "forward")
    dataset = campaign.get("dataset_provenance")
    dataset = dataset if isinstance(dataset, dict) else {}
    files = dataset.get("files")
    file_rows = files if isinstance(files, list) else []
    files_complete = bool(file_rows) and all(
        isinstance(row, dict)
        and row.get("exists") is True
        and isinstance(row.get("fingerprint"), str)
        and isinstance(row.get("path"), str)
        for row in file_rows
    )
    oos_ready = bool(
        oos
        and oos.get("sample_count") is not None
        and oos.get("anti_lookahead_receipt_valid") is True
        and oos.get("no_lookahead") is True
        and oos.get("purged") is True
    )
    forward_ready = bool(
        forward
        and forward.get("sample_count") is not None
        and forward.get("anti_lookahead_receipt_valid") is True
        and forward.get("no_lookahead") is True
        and forward.get("post_freeze") is True
        and forward.get("causal_live_only") is True
    )

    missing = [
        "BASELINE_CHALLENGER_COMPARISON_MISSING",
        "SAME_WINDOWS_COSTS_LATENCY_CAPACITY_UNPROVEN",
        "POINT_IN_TIME_COMPARISON_UNPROVEN",
        "TRIAL_ACCOUNTING_MISSING",
    ]
    if not oos_ready:
        missing.append("OOS_FROZEN_REPLAY_MISSING")
    if not forward_ready:
        missing.append("FORWARD_FROZEN_REPLAY_MISSING")
    if not files_complete:
        missing.append("SAFE_CORPUS_FILE_MANIFEST_INCOMPLETE")
    if task_scope == "H-T119":
        missing.extend(("SAFE_OOS_MISSING", "CROWDING_FOLLOWER_ABLATION_MISSING"))
    if task_scope == "H-T223":
        missing.extend(("KRONOS_FREEZE_SEPARATE_RECEIPT_REQUIRED", "FORECAST_REALIZED_REPORT_MISSING"))

    claims = {
        "same_corpus": False,
        "same_windows": False,
        "same_costs": False,
        "same_latency_capacity": False,
        "oos_frozen": oos_ready,
        "forward_frozen": forward_ready,
        "baseline_challenger_comparison": False,
        "point_in_time_only": False,
        "trial_accounting": False,
        "missing_values_not_zeroed": True,
        "dataset_provenance_bound": bool(dataset.get("dataset_fingerprint")) and files_complete,
        "ablation_follower_count": False,
        "safe_oos": False,
        "train_oos_forward": oos_ready and forward_ready,
        "forecast_realized_report": False,
        "append_only_results": False,
    }
    evidence_status = "PROVEN" if not missing else "UNMEASURABLE"
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": "economic_replay",
        "head_sha": head_sha,
        "task_scope": task_scope,
        "evidence_status": evidence_status,
        "decision": "GO" if evidence_status == "PROVEN" else "NO_GO",
        "paper_read_only": campaign.get("paper_read_only") is True,
        "real_execution": campaign.get("real_execution") is True,
        "source": {
            "campaign_path": str(campaign_path),
            "campaign_sha256": _sha256(campaign_path),
            "provenance_path": str(provenance_path),
            "provenance_sha256": _sha256(provenance_path),
            "dataset_fingerprint": dataset.get("dataset_fingerprint"),
            "source_status": campaign.get("source_status"),
        },
        "observed": {
            "objective_status": campaign.get("objective_status"),
            "dataset_provenance": dataset,
            "oos": oos,
            "forward": forward,
            "parameter_freeze": campaign.get("parameter_freeze"),
            "trade_ids_count": campaign.get("trade_ids_count"),
            "trade_ids_sha256": campaign.get("trade_ids_sha256"),
            "paper_read_only": campaign.get("paper_read_only"),
            "real_execution": campaign.get("real_execution"),
        },
        "claims": claims,
        "missing_evidence": sorted(set(missing)),
        "next_safe_action": (
            "Supply a complete SAFE corpus with a pre-registered baseline/challenger "
            "comparison, disjoint frozen OOS/FORWARD windows and retained receipts; "
            "for H-T119 add the real follower-count ablation and for H-T223 add the "
            "authoritative Kronos freeze and forecast-vs-realized report."
        ),
    }
    payload["receipt_sha256"] = _digest(payload)
    return payload


def append_to_wrapper(wrapper: Path, receipt: dict[str, Any]) -> None:
    existing = json.loads(wrapper.read_text(encoding="utf-8")) if wrapper.exists() else []
    if not isinstance(existing, list):
        raise ValueError("closure wrapper must be a JSON list")
    if not any(
        isinstance(item, dict) and item.get("receipt_sha256") == receipt.get("receipt_sha256")
        for item in existing
    ):
        existing.append(receipt)
    wrapper.write_text(
        json.dumps(existing, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--task-scope", choices=sorted(TASKS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wrapper", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        campaign = json.loads(args.campaign.read_text(encoding="utf-8"))
        provenance = json.loads(args.provenance.read_text(encoding="utf-8"))
        if not isinstance(campaign, dict) or not isinstance(provenance, dict):
            raise ValueError("campaign and provenance must be JSON objects")
        receipt = build_receipt(
            campaign,
            provenance,
            task_scope=args.task_scope,
            head_sha=_head_sha(args.repo_root),
            campaign_path=args.campaign,
            provenance_path=args.provenance,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if args.wrapper is not None:
            append_to_wrapper(args.wrapper, receipt)
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 1
    print(json.dumps({
        "output": str(args.output),
        "task_scope": args.task_scope,
        "status": receipt["evidence_status"],
        "decision": receipt["decision"],
        "head_sha": receipt["head_sha"],
        "missing_evidence_count": len(receipt["missing_evidence"]),
    }, sort_keys=True))
    return 0 if receipt["evidence_status"] == "PROVEN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
