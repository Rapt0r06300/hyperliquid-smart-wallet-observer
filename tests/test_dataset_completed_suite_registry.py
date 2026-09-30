from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.datasets.max_data_policy import (
    completed_suites_from_registry,
    record_completed_suite_from_result,
)

SHA = "a" * 40


def _write_result(lab: Path, path: Path, **overrides) -> Path:
    workspace = lab / "datasets" / "economic"
    workspace.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "alina.autonomous_research_result.v1",
        "job_id": "job-registry",
        "status": "SUCCESS",
        "suite": "economic-full",
        "mode": "economic",
        "project_sha": SHA,
        "workspace": str(workspace),
        "paper_only": True,
        "real_execution": False,
        "start_live_collection": False,
        "analysis_complete": True,
        "completion_recorded": True,
        "exit_code": 0,
    }
    payload.update(overrides)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_registry_helper_refuse_toute_reussite_ambigue(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    result_path = tmp_path / "result.json"

    for overrides in (
        {"exit_code": None},
        {"exit_code": False},
        {"exit_code": "0"},
        {"analysis_complete": False},
        {"analysis_complete": None},
        {"completion_recorded": False},
        {"completion_recorded": None},
    ):
        _write_result(lab, result_path, **overrides)
        with pytest.raises(ValueError):
            record_completed_suite_from_result(lab, result_path)

    assert completed_suites_from_registry(lab, project_sha=SHA) == ()


def test_registry_helper_accepte_uniquement_une_preuve_certifiee(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    result_path = _write_result(lab, tmp_path / "result.json")

    registry = record_completed_suite_from_result(lab, result_path)

    assert registry.is_file()
    assert completed_suites_from_registry(lab, project_sha=SHA) == ("economic-full",)


def test_registry_helper_refuse_live_non_paper_et_prepare_only(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    result_path = tmp_path / "result.json"

    for overrides in (
        {"paper_only": False},
        {"real_execution": True},
        {"start_live_collection": True},
        {"mode": "prepare-only"},
    ):
        _write_result(lab, result_path, **overrides)
        with pytest.raises(ValueError):
            record_completed_suite_from_result(lab, result_path)

    assert completed_suites_from_registry(lab, project_sha=SHA) == ()
