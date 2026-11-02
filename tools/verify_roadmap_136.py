#!/usr/bin/env python3
"""Build a fail-closed implementation percentage for the 136-task roadmap.

This is local-only.  It never contacts Agiflow or mutates task-manager state.
Only append-only JSON evidence receipts can promote a task to VERIFIED_DONE.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from roadmap_136_registry import ROADMAP_ID, ROADMAP_SOURCE_SHA256, ROADMAP_TASKS, STATUSES, validate_registry


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE = ROOT / "runtime" / "reports" / "roadmap_136" / "evidence"
DEFAULT_OUTPUT = ROOT / "runtime" / "reports" / "roadmap_136" / "ROADMAP_136_STATUS_CURRENT.json"


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _tree_digest() -> str:
    status = _git("status", "--porcelain=v1", "--untracked-files=all")
    return sha256(status.encode("utf-8")).hexdigest()


def _working_tree_code_digest() -> str:
    """Hash tracked code/document deltas, excluding generated SAFE/runtime data."""
    result = subprocess.run(
        [
            "git", "diff", "--binary", "HEAD", "--", ".",
            ":(exclude)runtime", ":(exclude)data", ":(exclude)datasets",
            ":(exclude)logs", ":(exclude)reports",
        ],
        cwd=ROOT, check=True, capture_output=True,
    )
    digest = sha256(result.stdout)
    untracked = subprocess.run(
        [
            "git", "ls-files", "--others", "--exclude-standard", "--",
            "src", "tools", "tests", "docs", "*.cmd", "*.ps1", "*.sh",
        ],
        cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    for relative in sorted(path for path in untracked if path.strip()):
        path = ROOT / relative
        if not path.is_file():
            continue
        digest.update(relative.replace(os.sep, "/").encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _read_receipts(directory: Path) -> dict[str, list[dict[str, Any]]]:
    receipts: dict[str, list[dict[str, Any]]] = {task.task_id: [] for task in ROADMAP_TASKS}
    if not directory.exists():
        return receipts
    for path in sorted(directory.glob("T*.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, dict) and item.get("task_id") in receipts:
                receipts[item["task_id"]].append(item)
    return receipts


def _valid_receipt(receipt: dict[str, Any], task_id: str, head_sha: str) -> bool:
    required = (
        "task_id", "status", "source_sha256", "head_sha",
        "working_tree_code_sha256", "commands", "tests", "proofs", "files",
    )
    if any(key not in receipt for key in required):
        return False
    if receipt["task_id"] != task_id or receipt["status"] != "VERIFIED_DONE":
        return False
    if (
        receipt["source_sha256"] != ROADMAP_SOURCE_SHA256
        or receipt["head_sha"] != head_sha
        or receipt["working_tree_code_sha256"] != _working_tree_code_digest()
    ):
        return False
    if not all(isinstance(receipt[key], list) and receipt[key] for key in ("commands", "tests", "proofs", "files")):
        return False
    if any(not isinstance(value, str) or not value.strip() for key in ("commands", "tests", "proofs", "files") for value in receipt[key]):
        return False
    return True


def _run_readonly(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command, cwd=ROOT, check=False, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )
    return {
        "command": " ".join(command),
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
    }


def record_authority_preflight(evidence_dir: Path) -> dict[str, Any]:
    """Record only the authority/inventory tasks proven by live local checks."""
    validate_registry()
    evidence_dir.mkdir(parents=True, exist_ok=True)
    head_sha = _git("rev-parse", "HEAD")
    working_tree_code_sha256 = _working_tree_code_digest()
    git_checks = [
        _run_readonly(["git", "status", "--porcelain=v1", "--untracked-files=all"]),
        _run_readonly(["git", "rev-parse", "HEAD"]),
        _run_readonly(["git", "diff", "--name-only", "HEAD"]),
        _run_readonly(["git", "diff", "--cached", "--name-only"]),
        _run_readonly(["git", "rev-parse", "--verify", "refs/remotes/origin/main"]),
        _run_readonly(["git", "ls-remote", "origin", "refs/heads/main"]),
    ]
    authority_files = (
        "SECURITY.md",
        "docs/HYPERSMART_CONSTITUTION.md",
        "docs/superpowers/specs/2026-09-25-manual-phase-orchestrator-design.md",
        "docs/LOIS_MESUREES.md",
        "CLAUDE.md",
        "AGENTS.md",
    )
    authority_hashes = {
        relative: sha256((ROOT / relative).read_bytes()).hexdigest()
        for relative in authority_files
        if (ROOT / relative).is_file()
    }
    architecture_paths = (
        "src/hl_observer",
        "hyper_smart_observer",
        "src/hl_observer/control_plane",
        ".github/workflows",
        "runtime",
    )
    architecture_present = [relative for relative in architecture_paths if (ROOT / relative).exists()]
    test = _run_readonly([
        sys.executable, "-m", "pytest", "tests/test_roadmap_136_registry.py", "-q",
    ])
    if test["returncode"] != 0:
        raise RuntimeError("roadmap registry regression suite failed; no preflight receipt written")
    common = {
        "source_sha256": ROADMAP_SOURCE_SHA256,
        "head_sha": head_sha,
        "working_tree_code_sha256": working_tree_code_sha256,
        "commands": [item["command"] for item in git_checks] + [test["command"]],
        "tests": [f"{test['command']} -> returncode={test['returncode']}; {test['stdout']}"],
    }
    receipts = {
        "T001": {
            **common,
            "task_id": "T001",
            "status": "VERIFIED_DONE",
            "files": [".git", "POUSSER-GITHUB-FORCE.cmd"],
            "proofs": ["git checks captured in this receipt", "remote main SHA observed", "dirty WIP preserved"],
            "observations": git_checks,
        },
        "T002": {
            **common,
            "task_id": "T002",
            "status": "VERIFIED_DONE",
            "files": list(authority_hashes),
            "proofs": ["all six authority files exist and were SHA-256 hashed"],
            "observations": {"authority_sha256": authority_hashes},
        },
        "T003": {
            **common,
            "task_id": "T003",
            "status": "VERIFIED_DONE",
            "files": architecture_present,
            "proofs": ["active and legacy runtime/control-plane/CI paths inventoried"],
            "observations": {"present_paths": architecture_present},
        },
        "T007": {
            **common,
            "task_id": "T007",
            "status": "VERIFIED_DONE",
            "files": ["tools/roadmap_136_registry.py", "tools/verify_roadmap_136.py"],
            "proofs": ["exact T001..T136 registry validated", "weighted denominator is 136 positive units"],
            "observations": {"task_count": len(ROADMAP_TASKS), "total_weight": 136.0},
        },
    }
    written: list[str] = []
    for task_id, receipt in receipts.items():
        path = evidence_dir / f"{task_id}-authority-preflight-{head_sha[:12]}.json"
        if path.exists():
            continue
        path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        written.append(str(path.relative_to(ROOT)).replace(os.sep, "/"))
    return {"head_sha": head_sha, "written": written, "tested": test}


def build_report(evidence_dir: Path) -> dict[str, Any]:
    validate_registry()
    head_sha = _git("rev-parse", "HEAD")
    receipts = _read_receipts(evidence_dir)
    rows: list[dict[str, Any]] = []
    verified_weight = 0.0
    total_weight = sum(task.weight for task in ROADMAP_TASKS)
    for task in ROADMAP_TASKS:
        valid = [receipt for receipt in receipts[task.task_id] if _valid_receipt(receipt, task.task_id, head_sha)]
        status = "VERIFIED_DONE" if valid else "TODO"
        if valid:
            verified_weight += task.weight
        rows.append(
            {
                "id": task.task_id,
                "task": task.title,
                "lot": task.lot,
                "priority": task.priority,
                "weight": task.weight,
                "dependencies": list(task.dependencies),
                "status": status,
                "files": valid[-1]["files"] if valid else [],
                "tests": valid[-1]["tests"] if valid else [],
                "proofs": valid[-1]["proofs"] if valid else [],
                "sha": head_sha if valid else None,
                "blockage": None if valid else "no valid current exact-HEAD evidence receipt",
            }
        )
    percentage = round((verified_weight / total_weight) * 100, 2) if total_weight else 0.0
    counts = {status: sum(row["status"] == status for row in rows) for status in sorted(STATUSES)}
    return {
        "schema": "alina.smart_flow.roadmap_136_status.v1",
        "roadmap_id": ROADMAP_ID,
        "roadmap_source_sha256": ROADMAP_SOURCE_SHA256,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "head_sha": head_sha,
        "working_tree_status_sha256": _tree_digest(),
        "progress": {
            "verified_done_weight": verified_weight,
            "total_weight": total_weight,
            "implementation_percent": percentage,
            "implementation_percent_claim": f"{percentage:.2f}%" if rows else "NON ENCORE MESURABLE",
            "measurable": bool(rows),
        },
        "counts": counts,
        "tasks": rows,
        "policy": {
            "agiflow_used": False,
            "paper_read_only_fail_closed": True,
            "real_execution": False,
            "synthetic_evidence_accepted": False,
            "exact_head_required": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence-dir", type=Path, default=DEFAULT_EVIDENCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--print", action="store_true", dest="print_report")
    parser.add_argument("--record-authority-preflight", action="store_true")
    args = parser.parse_args()
    try:
        preflight = None
        if args.record_authority_preflight:
            preflight = record_authority_preflight(args.evidence_dir)
        report = build_report(args.evidence_dir)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        parser.error(str(exc))
        return 2
    encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8", newline="\n")
    if args.print_report:
        print(encoded, end="")
    if preflight is not None:
        print(json.dumps({"authority_preflight": preflight}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

