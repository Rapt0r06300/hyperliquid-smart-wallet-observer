"""Explicit autonomous worker for active-family FULL/COLD economic suites.

It reuses the canonical worker's process/status/result helpers but never mutates
its globals. The family suite remains explicit from request validation through
workspace selection and result provenance.
"""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.datasets.archive_library import resolve_current_workspace
from hl_observer.datasets.economic_memory import EconomicMemoryError, record_certified_proof
from hl_observer.datasets.replay_workspace import prepare_replay_workspace
from hl_observer.ops import autonomous_research_job as canonical_job
from hl_observer.ops.autonomous_research_status import status_path, write_status

FAMILY_ECONOMIC_SUITES = frozenset(
    {"copy-vault-full", "lead-lag-full", "cross-venue-full"}
)
SUITE_CAMPAIGN_FAMILY = {
    "copy-vault-full": "copy_vault",
    "lead-lag-full": "lead_lag",
    "cross-venue-full": "cross_venue_dislocation_v2",
}
SUITE_COVERAGE_FAMILY = {
    "copy-vault-full": "copy_vault",
    "lead-lag-full": "lead_lag",
    "cross-venue-full": "cross_venue",
}
MEMORY_FAILURE_EXIT_CODE = 25


def validate_family_request(raw: Mapping[str, Any]) -> dict[str, Any]:
    suite = str(raw.get("suite") or "").strip()
    if str(raw.get("mode") or "").strip() != "economic" or suite not in FAMILY_ECONOMIC_SUITES:
        raise ValueError("family economic worker accepts only active-family FULL/COLD economic suites")
    # Reuse every canonical bound/guard while replacing only the canonical suite
    # allowlist check with a known-safe economic suite. Restore the original suite
    # immediately in the returned immutable request data.
    shim = dict(raw)
    shim["suite"] = "economic-full"
    validated = canonical_job.validate_request(shim)
    validated["suite"] = suite
    return validated


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"certification JSON unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"certification JSON object expected: {path}")
    return value


def record_family_economic_memory(
    *,
    lab_root: Path,
    workspace: Path,
    suite: str,
    project_sha: str,
) -> dict[str, Any] | None:
    """Persist only a fully eligible +4 USD family proof with exact provenance.

    A technically successful analysis below target simply returns ``None``. If
    a campaign claims ATTEINT but its FULL coverage, freeze or dataset identity
    is incomplete, this fails closed instead of storing an ambiguous proof.
    """
    campaign_family = SUITE_CAMPAIGN_FAMILY.get(suite)
    coverage_family = SUITE_COVERAGE_FAMILY.get(suite)
    if campaign_family is None or coverage_family is None:
        raise RuntimeError(f"unsupported economic memory suite: {suite}")
    campaign_path = workspace / "runtime" / "reports" / "economic_campaigns" / f"{campaign_family}.json"
    campaign = _load_json_object(campaign_path)
    if campaign.get("family") != campaign_family:
        raise RuntimeError("campaign family/provenance mismatch")
    if campaign.get("objective_status") != "ATTEINT":
        return None
    if campaign.get("paper_read_only") is not True or campaign.get("real_execution") is not False:
        raise RuntimeError("economic campaign lost paper/read-only guards")
    eligible_net = campaign.get("eligible_net_pnl_usd")
    if eligible_net is None or float(eligible_net) < 4.0:
        raise RuntimeError("ATTEINT campaign has no eligible >=4 USD proof")

    coverage_path = workspace / "runtime" / "reports" / "datasets" / "SOURCE_CONSUMPTION_COVERAGE.json"
    coverage = _load_json_object(coverage_path)
    families = coverage.get("families") if isinstance(coverage.get("families"), Mapping) else {}
    row = families.get(coverage_family) if isinstance(families, Mapping) else None
    if not isinstance(row, Mapping):
        raise RuntimeError(f"FULL source coverage missing for {coverage_family}")
    if str(row.get("status") or "") != "FULL" or int(row.get("discovered_files") or 0) <= 0:
        raise RuntimeError(f"source coverage is not FULL for {coverage_family}")

    datasets = campaign.get("dataset_provenance") if isinstance(campaign.get("dataset_provenance"), Mapping) else {}
    freeze = campaign.get("parameter_freeze") if isinstance(campaign.get("parameter_freeze"), Mapping) else {}
    dataset_sha = str(datasets.get("dataset_fingerprint") or "")
    config_sha = str(freeze.get("parameters_sha256") or "")
    runtime_sha = hashlib.sha256(campaign_path.read_bytes()).hexdigest()
    return record_certified_proof(
        lab_root,
        project_sha=project_sha,
        family=campaign_family,
        dataset_snapshot_sha256=dataset_sha,
        config_sha256=config_sha,
        suite=suite,
        runtime_proof_sha256=runtime_sha,
        net_pnl_usd=eligible_net,
        analysis_complete=True,
        certified=True,
        paper_only=True,
        real_execution=False,
    )


def execute_family_job(
    request_file: Path,
    *,
    project_root: Path,
    lab_root: Path,
    result_dir: Path,
    force: bool = False,
) -> int:
    request = validate_family_request(canonical_job._load_request(request_file))
    digest = canonical_job.request_digest(request)
    project_root = project_root.resolve()
    lab_root = lab_root.resolve()
    result_dir = result_dir.resolve()
    lab_root.mkdir(parents=True, exist_ok=True)
    live_path = status_path(lab_root)
    job_started = time.time()
    live_context: dict[str, Any] = {
        "job_id": request["job_id"],
        "suite": request["suite"],
        "mode": request["mode"],
        "job_started_unix": job_started,
        "workspace": None,
    }
    write_status(
        live_path,
        job_id=request["job_id"], suite=request["suite"], mode=request["mode"],
        state="STARTING", action_fr="Vérification du job économique famille",
        message_fr="Alina vérifie le SHA, la sécurité et la suite FULL/COLD avant tout calcul.",
        job_started_unix=job_started, step_index=1, step_total=5,
        next_action_fr="Préparer les données FULL/COLD de la famille",
    )

    canonical_job._assert_execution_disabled()
    actual_sha = canonical_job._git_head(project_root)
    if actual_sha != request["project_sha"]:
        raise RuntimeError(
            f"SHA projet différent: requête={request['project_sha']} checkout={actual_sha}. Refus reproductible."
        )

    completion = result_dir / "JOB_RESULT.json"
    if completion.is_file() and not force:
        try:
            previous = json.loads(completion.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None
        if (
            isinstance(previous, Mapping)
            and previous.get("request_digest") == digest
            and previous.get("project_sha") == actual_sha
            and previous.get("suite") == request["suite"]
            and previous.get("status") == "SUCCESS"
            and previous.get("analysis_complete") is True
        ):
            print(f"[CACHE JOB OK] {request['job_id']} preuve complète identique déjà présente.", flush=True)
            write_status(
                live_path, job_id=request["job_id"], suite=request["suite"], mode=request["mode"],
                state="SUCCESS_CACHED", action_fr="Aucun recalcul nécessaire",
                message_fr="Même SHA, même suite et même demande déjà certifiés complets.",
                job_started_unix=job_started, step_index=4, step_total=5,
            )
            return 0

    log_dir = lab_root / "job_logs" / request["job_id"]
    steps: list[dict[str, Any]] = []
    workspace: Path | None = None
    primary_rc = 0

    if request["download"]:
        prepare_cmd = [
            canonical_job.sys.executable, "-m", "hl_observer.ops.dataset_bridge", "prepare",
            "--root", str(lab_root), "--repo", request["dataset_repository"],
            "--release-id", str(request["release_id"]), "--suite", request["suite"],
            "--download", "--max-download-gib", str(request["max_download_gib"]),
            "--heartbeat-seconds", "1",
        ]
        step = canonical_job._run_logged(
            "01_prepare_dataset", prepare_cmd, cwd=project_root, log_dir=log_dir,
            live_status_path=live_path, live_context=live_context,
            action_fr="Préparation FULL/COLD de la famille",
            next_action_fr="Vérifier le workspace et le dataset non fiable", step_index=2, step_total=5,
        )
        steps.append(step)
        if step["return_code"] != 0:
            primary_rc = int(step["return_code"] or 2)

    if primary_rc == 0:
        try:
            workspace = resolve_current_workspace(lab_root, request["suite"])
        except Exception as exc:
            if not request["download"]:
                raise RuntimeError("Aucun workspace préparé et download=false.") from exc
            raise
        prepare_replay_workspace(project_root, materialized_root=workspace)
        live_context["workspace"] = str(workspace)

    if primary_rc == 0 and workspace is not None:
        step = canonical_job._run_logged(
            "02_economic_campaigns",
            [
                canonical_job.sys.executable,
                str(project_root / "tools" / "run_dataset_economic_campaigns.py"),
                "--root", str(workspace), "--no-start-collection",
                "--cross-budget-s", str(request["cross_budget_s"]),
                "--lead-history-sources", str(request["lead_history_sources"]),
            ],
            cwd=project_root, log_dir=log_dir,
            timeout_seconds=request["stage_timeout_seconds"], live_status_path=live_path,
            live_context=live_context,
            action_fr="Backtests économiques FULL/COLD de la famille",
            next_action_fr="Auditer les sources réellement consommées", step_index=3, step_total=5,
        )
        steps.append(step)
        primary_rc = int(step["return_code"])

    if primary_rc == 0 and workspace is not None:
        step = canonical_job._run_logged(
            "03_connection_audit",
            [canonical_job.sys.executable, "-m", "hl_observer.ops.dataset_connection_audit", "--root", str(workspace)],
            cwd=project_root, log_dir=log_dir, timeout_seconds=1800,
            live_status_path=live_path, live_context=live_context,
            action_fr="Vérification finale des sources et raccordements",
            next_action_fr="Sceller le résultat compact", step_index=4, step_total=5,
        )
        steps.append(step)
        if step["return_code"] != 0:
            primary_rc = int(step["return_code"])

    memory_record: dict[str, Any] | None = None
    memory_status = "NOT_EVALUATED"
    if primary_rc == 0 and workspace is not None:
        started_memory = time.monotonic()
        try:
            memory_record = record_family_economic_memory(
                lab_root=lab_root, workspace=workspace, suite=request["suite"], project_sha=actual_sha
            )
            memory_status = "CERTIFIED_RECORDED" if memory_record is not None else "TARGET_NOT_REACHED"
            steps.append({
                "name": "04_economic_memory", "return_code": 0, "timed_out": False,
                "duration_seconds": round(time.monotonic() - started_memory, 3),
                "status": memory_status,
            })
        except (RuntimeError, EconomicMemoryError, OSError, ValueError) as exc:
            memory_status = f"NO_GO:{type(exc).__name__}:{exc}"
            primary_rc = MEMORY_FAILURE_EXIT_CODE
            steps.append({
                "name": "04_economic_memory", "return_code": MEMORY_FAILURE_EXIT_CODE,
                "timed_out": False, "duration_seconds": round(time.monotonic() - started_memory, 3),
                "status": memory_status,
            })

    copied_reports = (
        canonical_job._collect_small_reports(project_root, workspace, result_dir, request["suite"])
        if workspace else []
    )
    status = "SUCCESS" if primary_rc == 0 else "NO_GO"
    payload = {
        "schema": "alina.autonomous_research_result.v1",
        "job_id": request["job_id"], "status": status, "suite": request["suite"],
        "mode": "economic", "request_digest": digest, "project_sha": actual_sha,
        "release_id": request["release_id"], "dataset_repository": request["dataset_repository"],
        "workspace": str(workspace) if workspace else None, "steps": steps,
        "copied_reports": copied_reports, "persistent_log_dir": str(log_dir),
        "paper_only": True, "real_execution": False, "start_live_collection": False,
        "network_market_data_used": False,
        "network_dataset_download_used": bool(request["download"]),
        "analysis_complete": False,
        "economic_memory_status": memory_status,
        "economic_memory_key": memory_record.get("key") if memory_record else None,
        "exit_code": primary_rc,
    }
    canonical_job._write_result(result_dir, payload)
    write_status(
        live_path, job_id=request["job_id"], suite=request["suite"], mode="economic",
        state=status, action_fr="Job famille terminé" if primary_rc == 0 else "Job famille NO_GO",
        message_fr="Pipeline technique terminé; le completion guard doit encore certifier la complétude."
        if primary_rc == 0 else "Une étape a échoué; aucune certification n'est enregistrée.",
        job_started_unix=job_started, step_index=4, step_total=5,
        workspace=str(workspace) if workspace else None, log_path=str(log_dir),
    )
    return primary_rc


__all__ = ["FAMILY_ECONOMIC_SUITES", "MEMORY_FAILURE_EXIT_CODE", "SUITE_CAMPAIGN_FAMILY", "execute_family_job", "record_family_economic_memory", "validate_family_request"]
