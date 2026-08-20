"""Ordered pre-FULL rehearsal and final GO evidence contract.

This module does not install a runner and never turns GO on by itself. It only
validates evidence supplied by CI/runtime. Missing evidence fails closed.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SCHEMA = "alina.pre_full_rehearsal.v1"
ORDERED_STAGES = (
    "unit",
    "integration",
    "ci",
    "dataset-deterministic",
    "economic-core",
    "small-real-corpus",
    "4-5gib",
    "crash-resume",
    "ram-profile",
    "disk-profile",
    "runtime-consumption",
    "family-suite",
    "economic-full",
    "microstructure-full",
    "research-lab-full",
    "sqlite-all-safe",
    "full-archive",
)
FINAL_GO_FLAGS = (
    "main_clean",
    "ci_green",
    "portable_linux_windows_ps51_green",
    "replay_forward_parity",
    "ledger_180g_catalogued",
    "runtime_consumption_proven",
    "no_fake_full",
    "checkpoints_ok",
    "crash_resume_ok",
    "bounded_memory",
    "pnl_reconciled",
    "three_families_certifiable",
    "anti_overfit_green",
    "placebos_green",
    "artifacts_sanitized",
    "permissions_secrets_green",
    "reproducible",
    "docs_current",
    "rehearsals_green",
)


def _valid_sha(value: object, length: int) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == length and all(ch in "0123456789abcdef" for ch in text)


def evaluate_rehearsals(payload: Mapping[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    if payload.get("schema") != SCHEMA:
        issues.append("SCHEMA_MISMATCH")
    if not _valid_sha(payload.get("project_sha"), 40):
        issues.append("PROJECT_SHA_MISSING")
    if payload.get("paper_only") is not True or payload.get("real_execution") is not False:
        issues.append("PAPER_READ_ONLY_GUARD_MISSING")
    rows = payload.get("stages")
    rows = rows if isinstance(rows, list) else []
    names = [str(row.get("name") or "") for row in rows if isinstance(row, Mapping)]
    if names != list(ORDERED_STAGES):
        issues.append("REHEARSAL_ORDER_OR_COVERAGE_INVALID")
    for expected, row in zip(ORDERED_STAGES, rows):
        if not isinstance(row, Mapping):
            issues.append(f"STAGE_INVALID:{expected}")
            continue
        if row.get("status") != "PASSED":
            issues.append(f"STAGE_NOT_PASSED:{expected}")
        if not _valid_sha(row.get("evidence_sha256"), 64):
            issues.append(f"STAGE_EVIDENCE_MISSING:{expected}")
    return {
        "ok": not issues,
        "issues": issues,
        "stages_expected": len(ORDERED_STAGES),
        "stages_passed": sum(
            1 for row in rows if isinstance(row, Mapping) and row.get("status") == "PASSED"
        ),
        "paper_only": True,
        "real_execution": False,
    }


def evaluate_final_go(payload: Mapping[str, Any]) -> dict[str, Any]:
    rehearsals = evaluate_rehearsals(payload)
    final = payload.get("final_go")
    final = final if isinstance(final, Mapping) else {}
    issues = list(rehearsals["issues"])
    for flag in FINAL_GO_FLAGS:
        if final.get(flag) is not True:
            issues.append(f"FINAL_GO_MISSING:{flag}")
    explicit = final.get("GO_SELF_HOSTED") == "TRUE"
    if not explicit:
        issues.append("GO_SELF_HOSTED_NOT_EXPLICIT_TRUE")
    return {
        "go": not issues,
        "issues": issues,
        "go_self_hosted": explicit,
        "rehearsals": rehearsals,
        "paper_only": True,
        "real_execution": False,
    }


def blank_evidence(project_sha: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "project_sha": project_sha,
        "paper_only": True,
        "real_execution": False,
        "stages": [
            {"name": name, "status": "PENDING", "evidence_sha256": None}
            for name in ORDERED_STAGES
        ],
        "final_go": {**{flag: False for flag in FINAL_GO_FLAGS}, "GO_SELF_HOSTED": "FALSE"},
    }


__all__ = [
    "FINAL_GO_FLAGS",
    "ORDERED_STAGES",
    "SCHEMA",
    "blank_evidence",
    "evaluate_final_go",
    "evaluate_rehearsals",
]
