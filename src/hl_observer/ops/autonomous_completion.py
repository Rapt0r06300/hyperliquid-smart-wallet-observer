"""Fail-closed completion contract for autonomous FULL/COLD research jobs.

The worker may technically return zero even when an historical stage was
SKIPPED because its required data was absent. This module turns the generated
reports into an explicit completion proof before a suite can be persisted in
COMPLETED_SUITES. It never sends data to GitHub and never touches an exchange.
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
ECONOMIC_FAMILY_BY_SUITE = {
    "copy-vault-full": "copy_vault",
    "lead-lag-full": "lead_lag",
    "cross-venue-full": "cross_venue",
}
FAMILY_ECONOMIC_REQUIRED_STEPS = {
    "copy-vault-full": ("02_economic_campaigns", "04_connection_audit"),
    "lead-lag-full": (
        "02_economic_campaigns",
        "03_lead_lag_causal_audit",
        "04_connection_audit",
    ),
    "cross-venue-full": ("02_economic_campaigns", "04_connection_audit"),
}
CANONICAL_ECONOMIC_REQUIRED_STEPS = (
    "02_economic_campaigns",
    "03_connection_audit",
)


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


def _explicit_zero(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        return int(value) == 0
    except (TypeError, ValueError, OverflowError):
        return False


def _required_economic_steps(suite: str) -> tuple[str, ...]:
    """Return the exact stage contract emitted by the selected economic worker.

    The canonical all-families worker still uses the historical
    ``03_connection_audit`` stage. Active family workers use the vNext stage
    numbering introduced when the Lead-Lag causal audit became an explicit
    stage: Copy-Vault/Cross-Venue finish on ``04_connection_audit`` and
    Lead-Lag must additionally prove ``03_lead_lag_causal_audit``.

    This mapping is intentionally fail-closed: an old/renamed stage cannot
    satisfy a family suite merely because it returned zero.
    """
    return FAMILY_ECONOMIC_REQUIRED_STEPS.get(
        str(suite or ""),
        CANONICAL_ECONOMIC_REQUIRED_STEPS,
    )


def _economic_contract(
    *,
    request: Mapping[str, Any],
    result: Mapping[str, Any],
    workspace: Path,
) -> dict[str, Any]:
    steps = _steps_by_name(result)
    suite = str(request.get("suite") or "")
    required_steps = _required_economic_steps(suite)
    incomplete_steps = [
        name
        for name in required_steps
        if name not in steps or not _explicit_zero(steps[name].get("return_code"))
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
    source_coverage_path = (
        workspace
        / "runtime"
        / "reports"
        / "datasets"
        / "SOURCE_CONSUMPTION_COVERAGE.json"
    )
    required_reports = (economic_report, connection_audit, source_coverage_path)
    missing_reports = [str(path) for path in required_reports if not path.is_file()]

    coverage_issues: list[str] = []
    coverage: dict[str, Any] = {}
    if source_coverage_path.is_file():
        coverage = _load_json(source_coverage_path)
        families = coverage.get("families")
        if not isinstance(families, Mapping):
            coverage_issues.append("SOURCE_COVERAGE_FAMILIES_MISSING")
            families = {}
        target_family = ECONOMIC_FAMILY_BY_SUITE.get(suite)
        if target_family is not None:
            family_row = families.get(target_family) if isinstance(families, Mapping) else None
            if not isinstance(family_row, Mapping):
                coverage_issues.append(f"SOURCE_COVERAGE_MISSING:{target_family}")
            else:
                try:
                    discovered = int(family_row.get("discovered_files") or 0)
                except (TypeError, ValueError, OverflowError):
                    discovered = 0
                if discovered <= 0:
                    coverage_issues.append(f"SOURCE_DISCOVERY_EMPTY:{target_family}")
                if str(family_row.get("status") or "") != "FULL":
                    coverage_issues.append(f"SOURCE_COVERAGE_NOT_FULL:{target_family}")
        else:
            if coverage.get("all_families_full") is not True:
                coverage_issues.append("SOURCE_COVERAGE_NOT_FULL:ALL_FAMILIES")
            discovered_total = 0
            if isinstance(families, Mapping):
                for row in families.values():
                    if not isinstance(row, Mapping):
                        continue
                    try:
                        discovered_total += max(0, int(row.get("discovered_files") or 0))
                    except (TypeError, ValueError, OverflowError):
                        continue
            if discovered_total <= 0:
                coverage_issues.append("SOURCE_DISCOVERY_EMPTY:ALL_FAMILIES")

    complete = not incomplete_steps and not missing_reports and not coverage_issues
    return {
        "schema": COMPLETION_SCHEMA,
        "mode": request.get("mode"),
        "suite": request.get("suite"),
        "analysis_complete": complete,
        "required_steps": list(required_steps),
        "incomplete_required_steps": incomplete_steps,
        "missing_required_reports": missing_reports,
        "source_coverage_report": str(source_coverage_path),
        "source_coverage_issues": coverage_issues,
        "source_coverage_all_families_full": coverage.get("all_families_full"),
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
    if result.get("status") != "SUCCESS" or not _explicit_zero(result.get("exit_code")):
        raise AutonomousCompletionError(
            "Le worker n'a pas produit un SUCCESS technique avec exit_code=0 explicite."
        )
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


def _persist_post_completion_economic_memory(
    *,
    result: dict[str, Any],
    result_path: Path,
    lab_root: Path,
) -> tuple[str, str | None]:
    """Persist the derived family-memory cache only after canonical completion.

    ``JOB_RESULT`` must already contain ``analysis_complete=true`` and
    ``completion_recorded=true`` on disk. Memory is a derived cache, not the
    source of completion truth: a cache-write failure is reported but never
    rewrites a valid canonical completion to NO_GO. The next identical cached
    invocation can retry it safely.
    """
    suite = str(result.get("suite") or "")
    if suite not in ECONOMIC_FAMILY_BY_SUITE:
        return str(result.get("economic_memory_status") or "NOT_APPLICABLE"), None
    if result.get("analysis_complete") is not True or result.get("completion_recorded") is not True:
        raise AutonomousCompletionError(
            "La mémoire économique ne peut être persistée avant completion_recorded=true."
        )

    on_disk = _load_json(result_path)
    if on_disk.get("analysis_complete") is not True or on_disk.get("completion_recorded") is not True:
        raise AutonomousCompletionError(
            "JOB_RESULT disque non finalisé avant persistance de la mémoire économique."
        )

    from hl_observer.ops.family_economic_job import record_family_economic_memory

    try:
        memory_record = record_family_economic_memory(
            lab_root=lab_root.resolve(),
            workspace=Path(str(result.get("workspace") or "")).resolve(),
            suite=suite,
            project_sha=str(result.get("project_sha") or ""),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        return f"CACHE_WRITE_FAILED:{type(exc).__name__}:{exc}", None

    if memory_record is None:
        return "TARGET_NOT_REACHED", None
    return "CERTIFIED_RECORDED", str(memory_record.get("key") or "") or None


def finalize_autonomous_completion(
    *,
    request_path: Path,
    project_root: Path,
    lab_root: Path,
    result_dir: Path,
) -> dict[str, Any]:
    """Validate completion, persist local truth, then derive optional caches.

    A prepare-only request stays a successful preparation but is never written
    to COMPLETED_SUITES. Any incomplete required analysis rewrites JOB_RESULT
    to NO_GO before raising so the public compact return cannot claim success.

    For active-family economic suites, certified economic memory is persisted
    only *after* the canonical completion registry and JOB_RESULT are durable.
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
            "Analyse incomplète: au moins une étape obligatoire ou une preuve de couverture manque."
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

    memory_status, memory_key = _persist_post_completion_economic_memory(
        result=result,
        result_path=result_path,
        lab_root=lab_root,
    )
    result["economic_memory_status"] = memory_status
    result["economic_memory_key"] = memory_key
    _atomic_json(result_path, result)

    return {
        **contract,
        "completion_recorded": True,
        "completion_registry_path": str(registry),
        "economic_memory_status": memory_status,
        "economic_memory_key": memory_key,
    }


__all__ = [
    "AutonomousCompletionError",
    "CANONICAL_ECONOMIC_REQUIRED_STEPS",
    "COMPLETION_EXIT_CODE",
    "COMPLETION_SCHEMA",
    "ECONOMIC_FAMILY_BY_SUITE",
    "FAMILY_ECONOMIC_REQUIRED_STEPS",
    "REGISTRY_EXIT_CODE",
    "build_completion_contract",
    "finalize_autonomous_completion",
]
