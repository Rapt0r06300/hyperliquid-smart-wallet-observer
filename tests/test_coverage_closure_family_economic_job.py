from __future__ import annotations

import json

import pytest

from hl_observer.ops import family_economic_job as family


SHA = "a" * 40


def _request(**overrides):
    value = {
        "job_id": "job-1",
        "suite": "copy-vault-full",
        "mode": "economic",
        "project_sha": SHA,
        "dataset_repository": "repo",
        "release_id": "release",
        "download": False,
        "max_download_gib": 1.0,
        "stage_timeout_seconds": 60,
        "cross_budget_s": 1.0,
        "lead_history_sources": 2,
    }
    value.update(overrides)
    return value


def test_validate_family_request_only_allows_active_economic_suites(monkeypatch) -> None:
    monkeypatch.setattr(family.canonical_job, "validate_request", lambda raw: dict(raw))
    for suite in family.FAMILY_ECONOMIC_SUITES:
        validated = family.validate_family_request(_request(suite=suite))
        assert validated["suite"] == suite
        assert validated["mode"] == "economic"
    with pytest.raises(ValueError):
        family.validate_family_request(_request(suite="economic-full"))
    with pytest.raises(ValueError):
        family.validate_family_request(_request(mode="historical"))


def test_load_json_object_success_and_failures(tmp_path) -> None:
    path = tmp_path / "x.json"
    path.write_text(json.dumps({"x": 1}), encoding="utf-8")
    assert family._load_json_object(path) == {"x": 1}
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(RuntimeError, match="object expected"):
        family._load_json_object(path)
    path.write_text("{", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unreadable"):
        family._load_json_object(path)
    with pytest.raises(RuntimeError, match="unreadable"):
        family._load_json_object(tmp_path / "missing.json")


def _campaign_workspace(tmp_path, *, suite="copy-vault-full", campaign=None, coverage=None):
    workspace = tmp_path / "workspace"
    campaign_family = family.SUITE_CAMPAIGN_FAMILY[suite]
    campaign_path = workspace / "runtime" / "reports" / "economic_campaigns" / f"{campaign_family}.json"
    campaign_path.parent.mkdir(parents=True, exist_ok=True)
    default_campaign = {
        "family": campaign_family,
        "paper_read_only": True,
        "real_execution": False,
        "objective_status": "MORE_DATA",
        "dataset_provenance": {"dataset_fingerprint": "d" * 64},
        "parameter_freeze": {"parameters_sha256": "c" * 64},
    }
    default_campaign.update(campaign or {})
    campaign_path.write_text(json.dumps(default_campaign), encoding="utf-8")
    coverage_path = workspace / "runtime" / "reports" / "datasets" / "SOURCE_CONSUMPTION_COVERAGE.json"
    coverage_path.parent.mkdir(parents=True, exist_ok=True)
    coverage_family = family.SUITE_COVERAGE_FAMILY[suite]
    default_coverage = {"families": {coverage_family: {"status": "FULL", "discovered_files": 1}}}
    if coverage is not None:
        default_coverage = coverage
    coverage_path.write_text(json.dumps(default_coverage), encoding="utf-8")
    return workspace, campaign_path


def test_record_family_memory_fail_closed_branches(monkeypatch, tmp_path) -> None:
    with pytest.raises(RuntimeError, match="unsupported"):
        family.record_family_economic_memory(lab_root=tmp_path, workspace=tmp_path, suite="bad", project_sha=SHA)

    workspace, _ = _campaign_workspace(tmp_path, campaign={"family": "wrong"})
    with pytest.raises(RuntimeError, match="family/provenance"):
        family.record_family_economic_memory(lab_root=tmp_path, workspace=workspace, suite="copy-vault-full", project_sha=SHA)

    workspace, _ = _campaign_workspace(tmp_path, campaign={"paper_read_only": False})
    with pytest.raises(RuntimeError, match="paper/read-only"):
        family.record_family_economic_memory(lab_root=tmp_path, workspace=workspace, suite="copy-vault-full", project_sha=SHA)

    workspace, _ = _campaign_workspace(tmp_path, campaign={"objective_status": "ATTEINT"})
    monkeypatch.setattr(family, "certify_campaign", lambda *args: {"certified": False, "reasons": ["OOS"]})
    with pytest.raises(RuntimeError, match="ATTEINT campaign failed"):
        family.record_family_economic_memory(lab_root=tmp_path, workspace=workspace, suite="copy-vault-full", project_sha=SHA)

    workspace, _ = _campaign_workspace(tmp_path, campaign={"objective_status": "MORE_DATA"})
    monkeypatch.setattr(family, "certify_campaign", lambda *args: {"certified": False, "reasons": []})
    assert family.record_family_economic_memory(lab_root=tmp_path, workspace=workspace, suite="copy-vault-full", project_sha=SHA) is None

    monkeypatch.setattr(family, "certify_campaign", lambda *args: {"certified": True, "eligible_net_pnl_usd": 3.99})
    with pytest.raises(RuntimeError, match=">=4 USD"):
        family.record_family_economic_memory(lab_root=tmp_path, workspace=workspace, suite="copy-vault-full", project_sha=SHA)

    workspace, _ = _campaign_workspace(tmp_path, coverage={"families": {}})
    monkeypatch.setattr(family, "certify_campaign", lambda *args: {"certified": True, "eligible_net_pnl_usd": 4.1})
    with pytest.raises(RuntimeError, match="coverage missing"):
        family.record_family_economic_memory(lab_root=tmp_path, workspace=workspace, suite="copy-vault-full", project_sha=SHA)

    workspace, _ = _campaign_workspace(tmp_path, coverage={"families": {"copy_vault": {"status": "PARTIAL", "discovered_files": 1}}})
    with pytest.raises(RuntimeError, match="not FULL"):
        family.record_family_economic_memory(lab_root=tmp_path, workspace=workspace, suite="copy-vault-full", project_sha=SHA)


def test_record_family_memory_success_records_canonical_proof(monkeypatch, tmp_path) -> None:
    workspace, _ = _campaign_workspace(tmp_path)
    monkeypatch.setattr(family, "certify_campaign", lambda *args: {"certified": True, "eligible_net_pnl_usd": 4.25})
    calls = []
    monkeypatch.setattr(family, "record_certified_proof", lambda root, **kwargs: calls.append((root, kwargs)) or {"saved": True})
    result = family.record_family_economic_memory(
        lab_root=tmp_path / "lab", workspace=workspace, suite="copy-vault-full", project_sha=SHA
    )
    assert result == {"saved": True}
    root, kwargs = calls[0]
    assert root == tmp_path / "lab"
    assert kwargs["family"] == "copy_vault"
    assert kwargs["net_pnl_usd"] == 4.25
    assert kwargs["paper_only"] is True and kwargs["real_execution"] is False
    assert kwargs["runtime_proof_sha256"]


def _wire_execute(monkeypatch, tmp_path, request, *, workspace=None, step_codes=(), prior_result=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    lab = tmp_path / "lab"
    result_dir = tmp_path / "result"
    req_file = tmp_path / "request.json"
    req_file.write_text(json.dumps(request), encoding="utf-8")
    monkeypatch.setattr(family.canonical_job, "_load_request", lambda path: dict(request))
    monkeypatch.setattr(family, "validate_family_request", lambda raw: dict(raw))
    monkeypatch.setattr(family.canonical_job, "request_digest", lambda req: "digest")
    monkeypatch.setattr(family.canonical_job, "_assert_execution_disabled", lambda: None)
    monkeypatch.setattr(family.canonical_job, "_git_head", lambda root: request["project_sha"])
    monkeypatch.setattr(family, "status_path", lambda root: root / "status.json")
    statuses = []
    monkeypatch.setattr(family, "write_status", lambda path, **kwargs: statuses.append(kwargs))
    if workspace is None:
        workspace = tmp_path / "workspace"
        workspace.mkdir(exist_ok=True)
    monkeypatch.setattr(family, "resolve_current_workspace", lambda root, suite: workspace)
    replay = []
    monkeypatch.setattr(family, "prepare_replay_workspace", lambda project_root, materialized_root: replay.append(materialized_root))
    codes = list(step_codes)
    steps = []

    def run_logged(name, cmd, **kwargs):
        code = codes.pop(0) if codes else 0
        row = {"name": name, "return_code": code, "cmd": cmd}
        steps.append(row)
        return row

    monkeypatch.setattr(family.canonical_job, "_run_logged", run_logged)
    monkeypatch.setattr(family.canonical_job, "_collect_small_reports", lambda *args: ["report.json"])
    written = []
    monkeypatch.setattr(family.canonical_job, "_write_result", lambda path, payload: written.append(dict(payload)))
    if prior_result is not None:
        result_dir.mkdir(parents=True, exist_ok=True)
        (result_dir / "JOB_RESULT.json").write_text(json.dumps(prior_result), encoding="utf-8")
    return req_file, project, lab, result_dir, workspace, statuses, steps, written, replay


def test_execute_family_job_sha_cache_and_no_download_workspace_failure(monkeypatch, tmp_path) -> None:
    request = _request()
    req_file, project, lab, result_dir, workspace, statuses, steps, written, replay = _wire_execute(monkeypatch, tmp_path, request)
    monkeypatch.setattr(family.canonical_job, "_git_head", lambda root: "b" * 40)
    with pytest.raises(RuntimeError, match="SHA projet différent"):
        family.execute_family_job(req_file, project_root=project, lab_root=lab, result_dir=result_dir)

    cached = {
        "request_digest": "digest", "project_sha": SHA, "suite": request["suite"],
        "status": "SUCCESS", "analysis_complete": True,
    }
    req_file, project, lab, result_dir, workspace, statuses, steps, written, replay = _wire_execute(
        monkeypatch, tmp_path / "cache", request, prior_result=cached
    )
    assert family.execute_family_job(req_file, project_root=project, lab_root=lab, result_dir=result_dir) == 0
    assert any(row["state"] == "SUCCESS_CACHED" for row in statuses)

    req_file, project, lab, result_dir, workspace, statuses, steps, written, replay = _wire_execute(monkeypatch, tmp_path / "missing", request)
    monkeypatch.setattr(family, "resolve_current_workspace", lambda *args: (_ for _ in ()).throw(FileNotFoundError("none")))
    with pytest.raises(RuntimeError, match="download=false"):
        family.execute_family_job(req_file, project_root=project, lab_root=lab, result_dir=result_dir)


def test_execute_family_job_success_download_and_step_failures(monkeypatch, tmp_path) -> None:
    request = _request(download=True)
    req_file, project, lab, result_dir, workspace, statuses, steps, written, replay = _wire_execute(monkeypatch, tmp_path, request, step_codes=[0, 0, 0])
    rc = family.execute_family_job(req_file, project_root=project, lab_root=lab, result_dir=result_dir)
    assert rc == 0
    assert [step["name"] for step in steps] == ["01_prepare_dataset", "02_economic_campaigns", "03_connection_audit"]
    assert replay == [workspace]
    payload = written[-1]
    assert payload["status"] == "SUCCESS"
    assert payload["analysis_complete"] is False
    assert payload["economic_memory_status"] == "PENDING_COMPLETION_GUARD"
    assert payload["paper_only"] is True and payload["real_execution"] is False
    assert payload["network_dataset_download_used"] is True

    request = _request(download=True)
    req_file, project, lab, result_dir, workspace, statuses, steps, written, replay = _wire_execute(monkeypatch, tmp_path / "prepare-fail", request, step_codes=[7])
    assert family.execute_family_job(req_file, project_root=project, lab_root=lab, result_dir=result_dir) == 7
    assert written[-1]["status"] == "NO_GO"
    assert written[-1]["workspace"] is None

    request = _request(download=False)
    req_file, project, lab, result_dir, workspace, statuses, steps, written, replay = _wire_execute(monkeypatch, tmp_path / "campaign-fail", request, step_codes=[5])
    assert family.execute_family_job(req_file, project_root=project, lab_root=lab, result_dir=result_dir) == 5
    assert written[-1]["status"] == "NO_GO"

    request = _request(download=False)
    req_file, project, lab, result_dir, workspace, statuses, steps, written, replay = _wire_execute(monkeypatch, tmp_path / "audit-fail", request, step_codes=[0, 6])
    assert family.execute_family_job(req_file, project_root=project, lab_root=lab, result_dir=result_dir) == 6
    assert [s["name"] for s in steps] == ["02_economic_campaigns", "03_connection_audit"]
