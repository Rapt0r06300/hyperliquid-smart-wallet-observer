#!/usr/bin/env python3
"""Run the local Copy-Vault replay and emit a fail-closed evidence receipt.

The local runner can establish that a deterministic TRAIN-only diagnostic ran,
but it cannot turn missing OOS/FORWARD or ablation observations into proof.
The receipt therefore preserves measured counts and the runner's exact reason,
while keeping the decision ``NO_GO`` until the required held-out evidence is
actually present.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "src"))

from hl_observer.backtesting.copy_vault_local_lab import run_historical_trade_replay

SCHEMA = "hypersmart.copy_vault.economic_replay_receipt.v1"


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


def build_receipt(
    result: dict[str, Any], *,
    task_scope: str,
    head_sha: str,
    source_path: Path,
) -> dict[str, Any]:
    source_count = result.get("source_trade_count")
    source_days = result.get("source_distinct_days")
    trial_count = result.get("trial_count")
    economically_proven = result.get("economically_proven") is True
    missing: list[str] = []
    if not economically_proven:
        missing.append("ECONOMIC_PROOF_NOT_PROVEN")
    if result.get("oos") is None:
        missing.append("OOS_FROZEN_REPLAY_MISSING")
    if result.get("forward") is None:
        missing.append("FORWARD_FROZEN_REPLAY_MISSING")
    if result.get("report") is None:
        missing.append("CANONICAL_REPORT_MISSING")
    if task_scope == "H-T119":
        missing.append("CROWDING_FOLLOWER_ABLATION_MISSING")

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "kind": "economic_replay",
        "head_sha": head_sha,
        "task_scope": task_scope,
        "evidence_status": "PROVEN" if not missing else "UNMEASURABLE",
        "decision": "GO" if not missing else "NO_GO",
        "paper_read_only": result.get("paper_read_only") is True,
        "real_execution": result.get("real_execution") is True,
        "source": {
            "path": str(source_path),
            "sha256": _sha256(source_path),
            "trade_count": source_count,
            "distinct_days": source_days,
        },
        "replay": {
            "status": result.get("status"),
            "reason": result.get("reason"),
            "trial_count": trial_count,
            "baseline": result.get("baseline"),
            "oos": result.get("oos"),
            "forward": result.get("forward"),
            "report": result.get("report"),
            "economically_proven": economically_proven,
        },
        "claims": {
            "same_corpus": False,
            "oos_frozen": False,
            "forward_frozen": False,
            "baseline_challenger_comparison": False,
            "ablation_follower_count": False,
            "missing_values_not_zeroed": True,
        },
        "missing_evidence": sorted(set(missing)),
        "next_safe_action": (
            "Supply the same SAFE corpus with disjoint frozen OOS/FORWARD windows "
            "and retained trajectory receipts; for H-T119 also supply the real "
            "crowding/follower-count ablation."
        ),
    }
    receipt["receipt_sha256"] = _digest(receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--task-scope", choices=("H-T99", "H-T119", "H-T223"), required=True)
    parser.add_argument("--bootstrap-samples", type=int, default=1000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_historical_trade_replay(args.repo_root, bootstrap_samples=args.bootstrap_samples)
        source_path = args.repo_root / str(result["source"])
        receipt = build_receipt(
            result,
            task_scope=args.task_scope,
            head_sha=_head_sha(args.repo_root),
            source_path=source_path,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8", newline="\n",
        )
    except (OSError, RuntimeError, TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 1
    print(json.dumps({
        "output": str(args.output),
        "task_scope": receipt["task_scope"],
        "status": receipt["evidence_status"],
        "decision": receipt["decision"],
        "head_sha": receipt["head_sha"],
        "source_trade_count": receipt["source"]["trade_count"],
        "source_distinct_days": receipt["source"]["distinct_days"],
        "trial_count": receipt["replay"]["trial_count"],
    }, sort_keys=True))
    return 0 if receipt["evidence_status"] == "PROVEN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
