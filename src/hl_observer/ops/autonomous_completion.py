"""Fail-closed completion contract for autonomous FULL/COLD research jobs.

The worker may technically return zero even when an historical stage was
SKIPPED because its required data was absent.  This module turns the generated
reports into an explicit completion proof before a suite can be persisted in
COMPLETED_SUITES.  It never sends data to GitHub and never touches an exchange.
"""
from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.datasets.max_data_policy import (
    ANALYSIS_MODES,
    record_completed_suite,
)
from hl_observer.ops.dataset_research_runner import build_dataset_stage_plan

COMPLETION_SCHEMA = "alina.autonomous_completion_contract.v1"
RESULT_SCHEMA = "alina.autonomous_research_result.v1"
REQUEST_SCHEMA = "alina.autonomous_research_job.v1"
COMPLETION_EXIT_CODE = 23
REGISTRY_EXIT_CODE = 24


class AutonomousCompletionError(RuntimeError):
    """The autonomous computation cannot be certified as complete."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AutonomousCompletionError(f"JSON de complétude illisible: {path}") from exc
    if not isinstance(raw, dict):
        raise AutonomousCompletionError(f"Objet JSON attendu: {path}")
    return raw


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _steps_by_name(result: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    rows = result.get("steps")
    if not isinstance(rows, list):
        return {}
    return {
        str(row.get("name") or ""): row
        for row in rows
        if isinstance(row, Mapping) and str(row.get("name") or "")
    }


def _economic_contract(
    *,
    request: Mapping[str, Any],
    result: Mapping[str, Any],
    workspace: Path,
) -> dict[str, Any]:
    steps = _steps_by_name(result)
    required_steps = ("02_economic_campaigns", "03_connection_audit")
    incomplete_steps = [
        name
        for name in required_steps
        if name not in steps or int(steps[name].get("return_code") or 0) != 0
    ]
    economic_report = (
        workspace
        / "runtime"
        / "reports"
        / "economic_campaigns"
        / "HYPERSMART_ECONOMIC_OBJECTIVE_CAMPAIGN.md"
    )
    connection_audit = (
        workspace
        / "runtime"
        / "reports"
        / "datasets"
        / "DATASET_CONNECTION_AUDIT.json"
    )
    missing_reports = [
        str(path)
        for path in (economic_report, connection_audit)
        if not path.is_file()
    ]
    complete = not incomplete_steps and not missing_reports
    return {
        "schema": COMPLETION_SCHEMA,
        "mode": request.get("mode"),
        "suite": request.get("suite"),
        "analysis_complete": complete,
        "required_steps": list(required_steps),
        "incomplete_required_steps": incomplete_steps,
        "missing_required_reports": missing_reports,
        "economic_report": str(economic_report),
        "connection_audit": str(connection_audit),
        "paper_only": True,
        "real_execution": False,
    }


def _historical_contract(
    *,
    request: Mapping[str, Any],
    result: Mapping[str, Any],
    project_root: Path,
    workspace: Path,
) -> dict[str, Any]:
    suite = str(request.get("suite") or "")
    mode = str(request.get("mode") or "")
    report_path = (
        project_root
        / "runtime"
        / "reports"
        / "datasets"
        / "historical"
        / suite
        / "report_dataset_latest.json"
    )
    report = _load_json(report_path)
    if str(report.get("dataset_suite") or "") != suite:
        raise AutonomousCompletionError(
            f"Le rapport historique ne prouve pas la suite demandée: {report_path}"
        )
    report_data_root = str(report.get("data_root") or "")
    if not report_data_root or Path(report_data_root).resolve() != workspace:
        raise AutonomousCompletionError(
            "Le rapport historique ne correspond pas au workspace du job courant."
        )

    raw_results = report.get("results")
    if not isinstance(raw_results, list):
        raise AutonomousCompletionError("Le rapport historique n'expose pas la liste des étapes.")
    statuses = {
        str(row.get("key") or ""): str(row.get("status") or "")
        for row in raw_results
        if isinstance(row, Mapping) and str(row.get("key") or "")
    }

    full = mode in {"historical-full", "historical-deep"}
    deep = mode == "historical-deep"
    plan = build_dataset_stage_plan(
        project_root,
        workspace,
        report_path.parent / "_completion_contract_unused",
        full=full,
        deep=deep,
        timeout_seconds=max(60, int(request.get("stage_timeout_seconds") or 3600)),
    )
    required_keys = [stage.key for stage in plan if not stage.optional]
    optional_keys = [stage.key for stage in plan if stage.optional]
    required_status = {key: statuses.get(key, "MISSING_RESULT") for key in required_keys}
    optional_status = {key: statuses.get(key, "NOT_RUN") for key in optional_keys}
    incomplete = [key for key, status in required_status.items() if status != "PASSED"]
    skipped = [key for key, status in required_status.items() if status == "SKIPPED"]
    failed = [key for key, status in required_status.items() if status == "FAILED"]
    interrupted = [key for key, status in required_status.items() if status == "INTERRUPTED"]
    missing = [key for key, status in required_status.items() if status == "MISSING_RESULT"]
    complete = bool(required_keys) and not incomplete

    contract = {
        "schema": COMPLETION_SCHEMA,
        "mode": mode,
        "suite": suite,
        "analysis_complete": complete,
        "historical_report": str(report_path),
        "required_stage_count": len(required_keys),
        "required_stage_passed": sum(status == "PASSED" for status in required_status.values()),
        "required_stage_incomplete": incomplete,
        "required_stage_skipped": skipped,
        "required_stage_failed": failed,
        "required_stage_interrupted": interrupted,
        "required_stage_missing_result": missing,
        "required_stage_status": required_status,
        "optional_stage_status": optional_status,
        "optional_stages_block_completion": False,
        "paper_only": True,
        "real_execution": False,
    }

    # Make the canonical historical report self-describing for later audits.
    report["autonomous_completion_contract"] = contract
    report["analysis_complete"] = complete
    _atomic_json(report_path, report)
    return contract


def build_completion_contract(
    *,
    request: Mapping[str, Any],
    result: Mapping[str, Any],
    project_root: Path,
    lab_root: Path,
) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA:
        raise AutonomousCompletionError("Schéma de requête autonome inattendu.")
    if result.get("schema") != RESULT_SCHEMA:
        raise AutonomousCompletionError("Schéma JOB_RESULT inattendu.")
    for key in ("job_id", "suite", "mode", "project_sha"):
        if str(request.get(key) or "") != str(result.get(key) or ""):
            raise AutonomousCompletionError(f"JOB_RESULT ne correspond pas à la requête: {key}")
    if result.get("status") != "SUCCESS" or int(result.get("exit_code") or 0) != 0:
        raise AutonomousCompletionError("Le worker n'a pas produit un SUCCESS technique avec exit_code=0.")
    if result.get("paper_only") is not True or result.get("real_execution") is not False:
        raise AutonomousCompletionError("JOB_RESULT sans garde paper/read-only stricte.")
    if result.get("start_live_collection") is not False:
        raise AutonomousCompletionError("Une collecte live ne peut pas compléter une suite FULL/COLD.")

    workspace_text = str(result.get("workspace") or "")
    if not workspace_text:
        raise AutonomousCompletionError("Workspace absent du JOB_RESULT.")
    workspace = Path(workspace_text).resolve()
    try:
        workspace.relative_to(lab_root.resolve())
    except ValueError as exc:
        raise AutonomousCompletionError("Workspace du job hors laboratoire persistant.") from exc

    mode = str(request.get("mode") or "")
    if mode == "prepare-only":
        return {
            "schema": COMPLETION_SCHEMA,
            "mode": mode,
            "suite": request.get("suite"),
            "analysis_complete": False,
            "completion_recordable": False,
            "reason": "PREPARE_ONLY_NEVER_COMPLETES_ANALYSIS",
            "paper_only": True,
            "real_execution": False,
        }
    if mode == "economic":
        return _economic_contract(request=request, result=result, workspace=workspace)
    if mode.startswith("historical"):
        return _historical_contract(
            request=request,
            result=result,
            project_root=project_root.resolve(),
            workspace=workspace,
        )
    raise AutonomousCompletionError(f"Mode autonome non certifiable: {mode}")


def finalize_autonomous_completion(
    *,
    request_path: Path,
    project_root: Path,
    lab_root: Path,
    result_dir: Path,
) -> dict[str, Any]:
    """Validate completion, persist the local registry and annotate JOB_RESULT.

    A prepare-only request stays a successful preparation but is never written
    to COMPLETED_SUITES.  Any incomplete required analysis rewrites JOB_RESULT
    to NO_GO before raising so the public compact return cannot claim success.
    """

    request = _load_json(request_path)
    result_path = result_dir.resolve() / "JOB_RESULT.json"
    result = _load_json(result_path)
    contract_path = result_dir.resolve() / "COMPLETION_CONTRACT.json"
    contract = build_completion_contract(
        request=request,
        result=result,
        project_root=project_root.resolve(),
        lab_root=lab_root.resolve(),
    )
    result["analysis_complete"] = contract.get("analysis_complete") is True
    result["completion_contract"] = contract
    result["completion_recorded"] = False
    result["completion_registry_path"] = None
    _atomic_json(contract_path, contract)

    mode = str(request.get("mode") or "")
    if mode == "prepare-only":
        _atomic_json(result_path, result)
        return contract

    if mode not in ANALYSIS_MODES:
        raise AutonomousCompletionError(f"Mode non analysant refusé: {mode}")
    if contract.get("analysis_complete") is not True:
        result["status"] = "NO_GO"
        result["exit_code"] = COMPLETION_EXIT_CODE
        result["completion_error"] = "REQUIRED_ANALYSIS_INCOMPLETE"
        _atomic_json(result_path, result)
        raise AutonomousCompletionError(
            "Analyse incomplète: au moins une étape obligatoire n'est pas PASSED."
        )

    try:
        registry = record_completed_suite(
            lab_root,
            suite=str(result.get("suite") or ""),
            mode=mode,
            job_id=str(result.get("job_id") or ""),
            project_sha=str(result.get("project_sha") or ""),
            workspace=str(result.get("workspace") or ""),
        )
    except (OSError, ValueError) as exc:
        result["status"] = "NO_GO"
        result["exit_code"] = REGISTRY_EXIT_CODE
        result["completion_error"] = f"COMPLETED_SUITES_WRITE_FAILED:{type(exc).__name__}:{exc}"
        _atomic_json(result_path, result)
        raise AutonomousCompletionError(
            f"Analyse complète mais registre COMPLETED_SUITES non écrit: {exc}"
        ) from exc

    result["completion_recorded"] = True
    result["completion_registry_path"] = str(registry)
    _atomic_json(result_path, result)
    return {**contract, "completion_recorded": True, "completion_registry_path": str(registry)}


__all__ = [
    "AutonomousCompletionError",
    "COMPLETION_EXIT_CODE",
    "COMPLETION_SCHEMA",
    "REGISTRY_EXIT_CODE",
    "build_completion_contract",
    "finalize_autonomous_completion",
]
