from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.datasets.max_data_policy import completed_suites_from_registry
from hl_observer.ops import autonomous_completion
from hl_observer.ops.historical_analysis_suite import AnalysisStage

SHA = "a" * 40


def _request(*, suite: str = "research-lab-full", mode: str = "historical-deep") -> dict:
    return {
        "schema": "alina.autonomous_research_job.v1",
        "job_id": "job-1",
        "suite": suite,
        "mode": mode,
        "project_sha": SHA,
        "stage_timeout_seconds": 3600,
    }


def _result(workspace: Path, *, suite: str = "research-lab-full", mode: str = "historical-deep") -> dict:
    return {
        "schema": "alina.autonomous_research_result.v1",
        "job_id": "job-1",
        "status": "SUCCESS",
        "suite": suite,
        "mode": mode,
        "project_sha": SHA,
        "workspace": str(workspace),
        "steps": [],
        "paper_only": True,
        "real_execution": False,
        "start_live_collection": False,
        "exit_code": 0,
    }


def _stage(key: str, *, optional: bool = False) -> AnalysisStage:
    return AnalysisStage(
        key=key,
        title=key,
        purpose="test",
        command=("python", "-c", "pass"),
        optional=optional,
    )


def _write_historical_report(
    project_root: Path,
    workspace: Path,
    *,
    rows: list[dict[str, object]],
    suite: str = "research-lab-full",
) -> Path:
    path = (
        project_root
        / "runtime"
        / "reports"
        / "datasets"
        / "historical"
        / suite
        / "report_dataset_latest.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "dataset_suite": suite,
                "data_root": str(workspace),
                "results": rows,
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_economic_reports(
    workspace: Path,
    *,
    family_status: dict[str, tuple[int, str]] | None = None,
) -> None:
    report = workspace / "runtime/reports/economic_campaigns/HYPERSMART_ECONOMIC_OBJECTIVE_CAMPAIGN.md"
    audit = workspace / "runtime/reports/datasets/DATASET_CONNECTION_AUDIT.json"
    coverage = workspace / "runtime/reports/datasets/SOURCE_CONSUMPTION_COVERAGE.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    audit.parent.mkdir(parents=True, exist_ok=True)
    coverage.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("# proof\n", encoding="utf-8")
    audit.write_text("{}\n", encoding="utf-8")
    statuses = family_status or {
        "copy_vault": (1, "FULL"),
        "lead_lag": (1, "FULL"),
        "cross_venue": (1, "FULL"),
    }
    families = {
        name: {
            "discovered_files": discovered,
            "consumed_files": discovered if status == "FULL" else 0,
            "status": status,
        }
        for name, (discovered, status) in statuses.items()
    }
    coverage.write_text(
        json.dumps(
            {
                "schema": "hypersmart.dataset_source_consumption_coverage.v1",
                "families": families,
                "all_families_full": bool(families)
                and all(row["status"] == "FULL" for row in families.values()),
            }
        ),
        encoding="utf-8",
    )


def _family_steps(suite: str) -> list[dict[str, object]]:
    return [
        {"name": name, "return_code": 0}
        for name in autonomous_completion.FAMILY_ECONOMIC_REQUIRED_STEPS[suite]
    ]


def test_required_skipped_is_not_a_complete_historical_suite(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    lab_root = tmp_path / "lab"
    workspace = lab_root / "datasets" / "research"
    workspace.mkdir(parents=True)
    _write_historical_report(
        project_root,
        workspace,
        rows=[
            {"key": "required_a", "status": "PASSED"},
            {"key": "required_b", "status": "SKIPPED"},
            {"key": "optional_c", "status": "SKIPPED"},
        ],
    )
    monkeypatch.setattr(
        autonomous_completion,
        "build_dataset_stage_plan",
        lambda *args, **kwargs: (
            _stage("required_a"),
            _stage("required_b"),
            _stage("optional_c", optional=True),
        ),
    )

    contract = autonomous_completion.build_completion_contract(
        request=_request(),
        result=_result(workspace),
        project_root=project_root,
        lab_root=lab_root,
    )

    assert contract["analysis_complete"] is False
    assert contract["required_stage_skipped"] == ["required_b"]
    assert contract["required_stage_incomplete"] == ["required_b"]
    assert contract["optional_stage_status"] == {"optional_c": "SKIPPED"}


def test_optional_skipped_does_not_block_complete_historical_suite(tmp_path: Path, monkeypatch) -> None:
    project_root = tmp_path / "project"
    lab_root = tmp_path / "lab"
    workspace = lab_root / "datasets" / "research"
    workspace.mkdir(parents=True)
    _write_historical_report(
        project_root,
        workspace,
        rows=[
            {"key": "required_a", "status": "PASSED"},
            {"key": "required_b", "status": "PASSED"},
            {"key": "optional_c", "status": "SKIPPED"},
        ],
    )
    monkeypatch.setattr(
        autonomous_completion,
        "build_dataset_stage_plan",
        lambda *args, **kwargs: (
            _stage("required_a"),
            _stage("required_b"),
            _stage("optional_c", optional=True),
        ),
    )

    contract = autonomous_completion.build_completion_contract(
        request=_request(),
        result=_result(workspace),
        project_root=project_root,
        lab_root=lab_root,
    )

    assert contract["analysis_complete"] is True
    assert contract["required_stage_passed"] == 2
    assert contract["required_stage_incomplete"] == []


def test_incomplete_historical_job_is_rewritten_no_go_and_not_registered(
    tmp_path: Path, monkeypatch
) -> None:
    project_root = tmp_path / "project"
    lab_root = tmp_path / "lab"
    workspace = lab_root / "datasets" / "research"
    result_dir = lab_root / "results" / "jobs" / "job-1"
    workspace.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    request_path = result_dir / "request.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")
    (result_dir / "JOB_RESULT.json").write_text(
        json.dumps(_result(workspace)), encoding="utf-8"
    )
    _write_historical_report(
        project_root,
        workspace,
        rows=[{"key": "required_a", "status": "SKIPPED"}],
    )
    monkeypatch.setattr(
        autonomous_completion,
        "build_dataset_stage_plan",
        lambda *args, **kwargs: (_stage("required_a"),),
    )

    with pytest.raises(autonomous_completion.AutonomousCompletionError):
        autonomous_completion.finalize_autonomous_completion(
            request_path=request_path,
            project_root=project_root,
            lab_root=lab_root,
            result_dir=result_dir,
        )

    rewritten = json.loads((result_dir / "JOB_RESULT.json").read_text(encoding="utf-8"))
    assert rewritten["status"] == "NO_GO"
    assert rewritten["exit_code"] == autonomous_completion.COMPLETION_EXIT_CODE
    assert rewritten["analysis_complete"] is False
    assert completed_suites_from_registry(lab_root, project_sha=SHA) == ()


def test_complete_economic_job_records_suite_for_exact_sha(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    lab_root = tmp_path / "lab"
    workspace = lab_root / "datasets" / "economic"
    result_dir = lab_root / "results" / "jobs" / "job-1"
    workspace.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    _write_economic_reports(workspace)

    request = _request(suite="economic-full", mode="economic")
    result = _result(workspace, suite="economic-full", mode="economic")
    result["steps"] = [
        {"name": "02_economic_campaigns", "return_code": 0},
        {"name": "03_connection_audit", "return_code": 0},
    ]
    request_path = result_dir / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    (result_dir / "JOB_RESULT.json").write_text(json.dumps(result), encoding="utf-8")

    contract = autonomous_completion.finalize_autonomous_completion(
        request_path=request_path,
        project_root=project_root,
        lab_root=lab_root,
        result_dir=result_dir,
    )

    assert contract["analysis_complete"] is True
    assert contract["completion_recorded"] is True
    assert completed_suites_from_registry(lab_root, project_sha=SHA) == ("economic-full",)
    final = json.loads((result_dir / "JOB_RESULT.json").read_text(encoding="utf-8"))
    assert final["status"] == "SUCCESS"
    assert final["analysis_complete"] is True
    assert final["completion_recorded"] is True


def test_economic_step_without_explicit_return_code_fails_closed(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    lab_root = tmp_path / "lab"
    workspace = lab_root / "datasets" / "economic"
    workspace.mkdir(parents=True)
    _write_economic_reports(workspace)
    request = _request(suite="economic-full", mode="economic")
    result = _result(workspace, suite="economic-full", mode="economic")
    result["steps"] = [
        {"name": "02_economic_campaigns"},
        {"name": "03_connection_audit", "return_code": 0},
    ]

    contract = autonomous_completion.build_completion_contract(
        request=request,
        result=result,
        project_root=project_root,
        lab_root=lab_root,
    )

    assert contract["analysis_complete"] is False
    assert contract["incomplete_required_steps"] == ["02_economic_campaigns"]


def test_family_economic_suite_requires_nonempty_full_source_coverage(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    lab_root = tmp_path / "lab"
    workspace = lab_root / "datasets" / "copy"
    workspace.mkdir(parents=True)
    _write_economic_reports(
        workspace,
        family_status={
            "copy_vault": (0, "FULL"),
            "lead_lag": (0, "FULL"),
            "cross_venue": (0, "FULL"),
        },
    )
    request = _request(suite="copy-vault-full", mode="economic")
    result = _result(workspace, suite="copy-vault-full", mode="economic")
    result["steps"] = _family_steps("copy-vault-full")

    contract = autonomous_completion.build_completion_contract(
        request=request,
        result=result,
        project_root=project_root,
        lab_root=lab_root,
    )

    assert contract["analysis_complete"] is False
    assert "SOURCE_DISCOVERY_EMPTY:copy_vault" in contract["source_coverage_issues"]


def test_family_economic_suite_accepts_full_nonempty_target_coverage(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    lab_root = tmp_path / "lab"
    workspace = lab_root / "datasets" / "lead"
    workspace.mkdir(parents=True)
    _write_economic_reports(
        workspace,
        family_status={
            "copy_vault": (0, "FULL"),
            "lead_lag": (3, "FULL"),
            "cross_venue": (0, "FULL"),
        },
    )
    request = _request(suite="lead-lag-full", mode="economic")
    result = _result(workspace, suite="lead-lag-full", mode="economic")
    result["steps"] = _family_steps("lead-lag-full")

    contract = autonomous_completion.build_completion_contract(
        request=request,
        result=result,
        project_root=project_root,
        lab_root=lab_root,
    )

    assert contract["analysis_complete"] is True
    assert contract["source_coverage_issues"] == []
    assert contract["required_steps"] == [
        "02_economic_campaigns",
        "03_lead_lag_causal_audit",
        "04_connection_audit",
    ]


@pytest.mark.parametrize(
    ("suite", "target_family"),
    [
        ("copy-vault-full", "copy_vault"),
        ("lead-lag-full", "lead_lag"),
        ("cross-venue-full", "cross_venue"),
    ],
)
def test_each_family_suite_accepts_only_its_exact_success_stage_contract(
    tmp_path: Path,
    suite: str,
    target_family: str,
) -> None:
    project_root = tmp_path / "project"
    lab_root = tmp_path / "lab"
    workspace = lab_root / "datasets" / suite
    workspace.mkdir(parents=True)
    statuses = {
        "copy_vault": (0, "FULL"),
        "lead_lag": (0, "FULL"),
        "cross_venue": (0, "FULL"),
    }
    statuses[target_family] = (2, "FULL")
    _write_economic_reports(workspace, family_status=statuses)
    request = _request(suite=suite, mode="economic")
    result = _result(workspace, suite=suite, mode="economic")
    result["steps"] = _family_steps(suite)

    contract = autonomous_completion.build_completion_contract(
        request=request,
        result=result,
        project_root=project_root,
        lab_root=lab_root,
    )

    assert contract["analysis_complete"] is True
    assert contract["required_steps"] == list(
        autonomous_completion.FAMILY_ECONOMIC_REQUIRED_STEPS[suite]
    )
    assert contract["incomplete_required_steps"] == []


@pytest.mark.parametrize(
    ("suite", "target_family", "missing_stage", "legacy_or_renamed_stage"),
    [
        ("copy-vault-full", "copy_vault", "04_connection_audit", "03_connection_audit"),
        (
            "lead-lag-full",
            "lead_lag",
            "03_lead_lag_causal_audit",
            "03_lead_lag_causal_diagnostic",
        ),
        ("cross-venue-full", "cross_venue", "04_connection_audit", "03_connection_audit"),
    ],
)
def test_family_suite_rejects_missing_or_renamed_required_stage(
    tmp_path: Path,
    suite: str,
    target_family: str,
    missing_stage: str,
    legacy_or_renamed_stage: str,
) -> None:
    project_root = tmp_path / "project"
    lab_root = tmp_path / "lab"
    workspace = lab_root / "datasets" / suite
    workspace.mkdir(parents=True)
    statuses = {
        "copy_vault": (0, "FULL"),
        "lead_lag": (0, "FULL"),
        "cross_venue": (0, "FULL"),
    }
    statuses[target_family] = (2, "FULL")
    _write_economic_reports(workspace, family_status=statuses)
    request = _request(suite=suite, mode="economic")
    result = _result(workspace, suite=suite, mode="economic")
    result["steps"] = [
        row
        for row in _family_steps(suite)
        if row["name"] != missing_stage
    ] + [{"name": legacy_or_renamed_stage, "return_code": 0}]

    contract = autonomous_completion.build_completion_contract(
        request=request,
        result=result,
        project_root=project_root,
        lab_root=lab_root,
    )

    assert contract["analysis_complete"] is False
    assert contract["incomplete_required_steps"] == [missing_stage]


def test_incomplete_family_job_never_reaches_registry_or_economic_memory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "project"
    lab_root = tmp_path / "lab"
    workspace = lab_root / "datasets" / "lead"
    result_dir = lab_root / "results" / "jobs" / "job-1"
    workspace.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    _write_economic_reports(
        workspace,
        family_status={
            "copy_vault": (0, "FULL"),
            "lead_lag": (3, "FULL"),
            "cross_venue": (0, "FULL"),
        },
    )
    request = _request(suite="lead-lag-full", mode="economic")
    result = _result(workspace, suite="lead-lag-full", mode="economic")
    result["steps"] = [
        {"name": "02_economic_campaigns", "return_code": 0},
        {"name": "04_connection_audit", "return_code": 0},
    ]
    request_path = result_dir / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    (result_dir / "JOB_RESULT.json").write_text(json.dumps(result), encoding="utf-8")
    memory_called = False

    def _forbidden_memory(**_kwargs):
        nonlocal memory_called
        memory_called = True
        raise AssertionError("economic memory must not run after an incomplete completion guard")

    monkeypatch.setattr(
        autonomous_completion,
        "_persist_post_completion_economic_memory",
        _forbidden_memory,
    )

    with pytest.raises(autonomous_completion.AutonomousCompletionError):
        autonomous_completion.finalize_autonomous_completion(
            request_path=request_path,
            project_root=project_root,
            lab_root=lab_root,
            result_dir=result_dir,
        )

    final = json.loads((result_dir / "JOB_RESULT.json").read_text(encoding="utf-8"))
    assert final["status"] == "NO_GO"
    assert final["analysis_complete"] is False
    assert final["completion_recorded"] is False
    assert completed_suites_from_registry(lab_root, project_sha=SHA) == ()
    assert memory_called is False


def test_missing_job_exit_code_is_never_implicit_success(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    lab_root = tmp_path / "lab"
    workspace = lab_root / "datasets" / "economic"
    workspace.mkdir(parents=True)
    _write_economic_reports(workspace)
    request = _request(suite="economic-full", mode="economic")
    result = _result(workspace, suite="economic-full", mode="economic")
    result.pop("exit_code")

    with pytest.raises(autonomous_completion.AutonomousCompletionError, match="exit_code=0 explicite"):
        autonomous_completion.build_completion_contract(
            request=request,
            result=result,
            project_root=project_root,
            lab_root=lab_root,
        )


def test_prepare_only_never_records_completed_suite(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    lab_root = tmp_path / "lab"
    workspace = lab_root / "datasets" / "economic"
    result_dir = lab_root / "results" / "jobs" / "job-1"
    workspace.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    request = _request(suite="economic-full", mode="prepare-only")
    result = _result(workspace, suite="economic-full", mode="prepare-only")
    request_path = result_dir / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    (result_dir / "JOB_RESULT.json").write_text(json.dumps(result), encoding="utf-8")

    contract = autonomous_completion.finalize_autonomous_completion(
        request_path=request_path,
        project_root=project_root,
        lab_root=lab_root,
        result_dir=result_dir,
    )

    assert contract["analysis_complete"] is False
    assert completed_suites_from_registry(lab_root, project_sha=SHA) == ()
    final = json.loads((result_dir / "JOB_RESULT.json").read_text(encoding="utf-8"))
    assert final["status"] == "SUCCESS"
    assert final["analysis_complete"] is False
    assert final["completion_recorded"] is False
