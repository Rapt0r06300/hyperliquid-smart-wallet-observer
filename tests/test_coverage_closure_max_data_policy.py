from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from hl_observer.datasets import max_data_policy as policy


SHA = "a" * 40


def test_number_sha_zero_and_empty_registry_helpers(tmp_path) -> None:
    assert policy._number("2.5") == 2.5
    for value in (None, "bad", -1, float("inf")):
        result = policy._number(value)
        if value == float("inf"):
            assert result == float("inf")
        else:
            assert result is None
    assert policy._valid_sha(SHA.upper()) is True
    assert policy._valid_sha("g" * 40) is False
    assert policy._explicit_zero(0) is True
    assert policy._explicit_zero(False) is False
    assert policy._explicit_zero("0") is False
    registry = policy._empty_completed_registry()
    assert registry["paper_only"] is True and registry["real_execution"] is False
    assert policy.completed_registry_path(tmp_path).name == "COMPLETED_SUITES.json"


def test_load_registry_missing_valid_and_fail_closed(tmp_path) -> None:
    assert policy.load_completed_suite_registry(tmp_path)["suites"] == {}
    path = policy.completed_registry_path(tmp_path)
    path.parent.mkdir(parents=True)
    valid = policy._empty_completed_registry()
    valid["suites"] = {"economic-full": {"suite": "economic-full"}, "bad": "ignored"}
    valid["history"] = [{"suite": "economic-full", "project_sha": SHA, "completed": True}, "ignored"]
    path.write_text(json.dumps(valid), encoding="utf-8")
    loaded = policy.load_completed_suite_registry(tmp_path)
    assert list(loaded["suites"]) == ["economic-full"]
    assert len(loaded["history"]) == 1
    assert policy.completed_suites_from_registry(tmp_path) == ("economic-full",)
    assert policy.completed_suites_from_registry(tmp_path, project_sha=SHA) == ("economic-full",)
    with pytest.raises(ValueError, match="project_sha invalide"):
        policy.completed_suites_from_registry(tmp_path, project_sha="bad")

    for bad in (
        {**valid, "schema": "bad"},
        {**valid, "suites": []},
        {**valid, "history": {}},
        {**valid, "paper_only": False},
        {**valid, "real_execution": True},
    ):
        path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError):
            policy.load_completed_suite_registry(tmp_path)


def test_record_completed_suite_validates_and_caps_history(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(policy, "suite_names", lambda: ("economic-full", "copy-vault-full"))
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path = policy.record_completed_suite(
        tmp_path,
        suite="economic-full",
        mode="economic",
        job_id="job-1",
        project_sha=SHA,
        workspace=workspace,
        completed_at_utc="2026-01-01T00:00:00+00:00",
    )
    raw = json.loads(path.read_text())
    assert raw["suites"]["economic-full"]["completed"] is True
    assert raw["paper_only"] is True and raw["real_execution"] is False

    with pytest.raises(ValueError, match="Suite inconnue"):
        policy.record_completed_suite(tmp_path, suite="bad", mode="economic", job_id="j", project_sha=SHA, workspace=workspace)
    with pytest.raises(ValueError, match="Mode non analysant"):
        policy.record_completed_suite(tmp_path, suite="economic-full", mode="prepare", job_id="j", project_sha=SHA, workspace=workspace)
    with pytest.raises(ValueError, match="job_id absent"):
        policy.record_completed_suite(tmp_path, suite="economic-full", mode="economic", job_id=" ", project_sha=SHA, workspace=workspace)
    with pytest.raises(ValueError, match="project_sha invalide"):
        policy.record_completed_suite(tmp_path, suite="economic-full", mode="economic", job_id="j", project_sha="bad", workspace=workspace)
    outside = tmp_path.parent / "outside-workspace"
    with pytest.raises(ValueError, match="hors du laboratoire"):
        policy.record_completed_suite(tmp_path, suite="economic-full", mode="economic", job_id="j", project_sha=SHA, workspace=outside)


def test_record_from_result_requires_full_certification(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(policy, "record_completed_suite", lambda root, **kwargs: kwargs)
    result_path = tmp_path / "JOB_RESULT.json"
    base = {
        "schema": "alina.autonomous_research_result.v1",
        "status": "SUCCESS",
        "exit_code": 0,
        "analysis_complete": True,
        "completion_recorded": True,
        "paper_only": True,
        "real_execution": False,
        "start_live_collection": False,
        "mode": "economic",
        "suite": "economic-full",
        "job_id": "j",
        "project_sha": SHA,
        "workspace": str(tmp_path / "w"),
    }
    result_path.write_text(json.dumps(base), encoding="utf-8")
    out = policy.record_completed_suite_from_result(tmp_path, result_path)
    assert out["suite"] == "economic-full"

    mutations = [
        ("schema", "bad"), ("status", "NO_GO"), ("exit_code", False),
        ("analysis_complete", False), ("completion_recorded", False),
        ("paper_only", False), ("real_execution", True),
        ("start_live_collection", True), ("mode", "prepare"),
    ]
    for key, value in mutations:
        bad = dict(base); bad[key] = value
        result_path.write_text(json.dumps(bad), encoding="utf-8")
        with pytest.raises(ValueError):
            policy.record_completed_suite_from_result(tmp_path, result_path)


def test_load_plans_top_family_ladder_and_targets(tmp_path) -> None:
    assert policy.load_suite_plans(tmp_path) == {}
    path = tmp_path / "runtime" / "reports" / "datasets" / "BIBLIOTHEQUE_180GO.json"
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    assert policy.load_suite_plans(tmp_path) == {}
    path.write_text(json.dumps({"plans": {"economic-full": {"download_gib": 2}, "bad": "x"}}), encoding="utf-8")
    assert policy.load_suite_plans(tmp_path) == {"economic-full": {"download_gib": 2}}

    decisions = [
        {"family": "lead_lag", "priority": 1},
        {"family": "copy_vault", "priority": 5},
        {"family": "unknown", "priority": 99},
    ]
    assert policy._top_family(decisions) == "copy_vault"
    assert policy._top_family([]) is None
    assert policy.suite_ladder("copy_vault")[1] == "copy-vault-full"
    assert len(policy.suite_ladder(None)) == len(set(policy.suite_ladder(None)))
    frozen = [{"family": family, "phase": "FREEZE_AND_CONFIRM_FORWARD"} for family in policy.REQUIRED_FAMILIES]
    assert policy.targets_reached_from_brain(frozen) is True
    frozen[0]["phase"] = "EXPLORE"
    assert policy.targets_reached_from_brain(frozen) is False


def test_choose_max_data_job_all_outcomes() -> None:
    decisions = [{"family": "copy_vault", "priority": 10}]
    plans = {
        "economic-full": {"missing_asset_count": 0, "remaining_download_gib": 3},
        "copy-vault-full": {"missing_asset_count": 0, "download_gib": 2},
    }
    stop = policy.choose_max_data_job(
        family_decisions=decisions, suite_plans=plans, free_disk_gib=100,
        all_targets_reached=True,
    )
    assert stop["status"] == "STOP_PROOF_REACHED"
    assert stop["download_budget_gib"] == 0.0

    ready = policy.choose_max_data_job(
        family_decisions=decisions, suite_plans=plans, completed_suites=(),
        free_disk_gib=100, all_targets_reached=False, reserve_gib=10,
    )
    assert ready["status"] == "READY"
    assert ready["recommended_suite"] == "economic-full"
    assert ready["recommended_mode"] == "economic"
    assert ready["holdout_used_for_ranking"] is False

    ready_family = policy.choose_max_data_job(
        family_decisions=decisions, suite_plans=plans, completed_suites=("economic-full",),
        free_disk_gib=100, all_targets_reached=False, reserve_gib=10,
    )
    assert ready_family["recommended_suite"] == "copy-vault-full"
    assert ready_family["recommended_mode"] == "historical-deep"
    assert ready_family["rejected_before_selection"][0]["reason"] == "ALREADY_COMPLETED_FOR_THIS_CODE"

    no_go = policy.choose_max_data_job(
        family_decisions=decisions,
        suite_plans={
            "economic-full": {"missing_asset_count": 1},
            "copy-vault-full": {"remaining_download_gib": "bad"},
            "microstructure-full": {"remaining_download_gib": 100},
        },
        completed_suites=(), free_disk_gib=20, all_targets_reached=False, reserve_gib=10,
    )
    assert no_go["status"] == "NO_GO"
    reasons = {row["reason"] for row in no_go["rejected"]}
    assert {"RELEASE_ASSETS_MISSING", "DOWNLOAD_SIZE_UNKNOWN", "INSUFFICIENT_DISK", "PLAN_MISSING"} <= reasons

    with pytest.raises(ValueError):
        policy.choose_max_data_job(family_decisions=[], suite_plans={}, free_disk_gib="bad", all_targets_reached=False)
    with pytest.raises(ValueError):
        policy.choose_max_data_job(family_decisions=[], suite_plans={}, free_disk_gib=100, reserve_gib=-1, all_targets_reached=False)


def test_write_decision_and_main_ready_and_no_go(monkeypatch, tmp_path, capsys) -> None:
    decision = {
        "status": "READY", "recommended_suite": "economic-full", "recommended_mode": "economic",
        "download_budget_gib": 4, "top_family": "copy_vault", "project_sha_scope": SHA,
        "reason": "unit", "suite_ladder": ["economic-full"],
    }
    json_path, md_path = policy.write_decision(tmp_path / "out", decision)
    assert json.loads(json_path.read_text())["status"] == "READY"
    assert "Compensation entre familles" in md_path.read_text()

    brain = tmp_path / "brain.json"
    brain.write_text(json.dumps({"family_decisions": [{"family": "copy_vault", "phase": "EXPLORE"}]}), encoding="utf-8")
    monkeypatch.setattr(policy, "load_suite_plans", lambda root: {"economic-full": {"remaining_download_gib": 0}})
    monkeypatch.setattr(policy, "completed_suites_from_registry", lambda root, project_sha=None: ())
    monkeypatch.setattr(policy.shutil, "disk_usage", lambda root: SimpleNamespace(free=100 * 1024**3))
    rc = policy.main(["--brain-json", str(brain), "--lab-root", str(tmp_path), "--output-dir", str(tmp_path / "main-out"), "--project-sha", SHA])
    assert rc == 0
    assert "ALINA_MAX_DATA status=READY" in capsys.readouterr().out

    monkeypatch.setattr(policy, "load_suite_plans", lambda root: {})
    with pytest.raises(ValueError, match="BIBLIOTHEQUE_180GO"):
        policy.main(["--brain-json", str(brain), "--lab-root", str(tmp_path), "--output-dir", str(tmp_path / "x")])
    brain.write_text(json.dumps({"family_decisions": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="family_decisions"):
        policy.main(["--brain-json", str(brain), "--lab-root", str(tmp_path), "--output-dir", str(tmp_path / "x")])
