from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.ops import autonomous_completion, family_economic_job

SHA = "a" * 40


def _request(*, suite: str = "copy-vault-full") -> dict[str, object]:
    return {
        "schema": autonomous_completion.REQUEST_SCHEMA,
        "job_id": "memory-order-test",
        "suite": suite,
        "mode": "economic",
        "project_sha": SHA,
        "stage_timeout_seconds": 3600,
    }


def _result(workspace: Path, *, suite: str = "copy-vault-full") -> dict[str, object]:
    steps = [{"name": "02_economic_campaigns", "return_code": 0}]
    if suite == "lead-lag-full":
        steps.append({"name": "03_lead_lag_causal_audit", "return_code": 0})
    steps.append({"name": "04_connection_audit", "return_code": 0})
    return {
        "schema": autonomous_completion.RESULT_SCHEMA,
        "job_id": "memory-order-test",
        "status": "SUCCESS",
        "suite": suite,
        "mode": "economic",
        "project_sha": SHA,
        "workspace": str(workspace),
        "steps": steps,
        "paper_only": True,
        "real_execution": False,
        "start_live_collection": False,
        "exit_code": 0,
        "economic_memory_status": "PENDING_COMPLETION_GUARD",
        "economic_memory_key": None,
    }


def _write_economic_reports(workspace: Path, *, discovered: int = 2) -> None:
    campaign_root = workspace / "runtime/reports/economic_campaigns"
    dataset_root = workspace / "runtime/reports/datasets"
    campaign_root.mkdir(parents=True, exist_ok=True)
    dataset_root.mkdir(parents=True, exist_ok=True)
    (campaign_root / "HYPERSMART_ECONOMIC_OBJECTIVE_CAMPAIGN.md").write_text(
        "# proof\n", encoding="utf-8"
    )
    (dataset_root / "DATASET_CONNECTION_AUDIT.json").write_text("{}\n", encoding="utf-8")
    (dataset_root / "SOURCE_CONSUMPTION_COVERAGE.json").write_text(
        json.dumps(
            {
                "families": {
                    "copy_vault": {
                        "status": "FULL",
                        "discovered_files": discovered,
                        "consumed_files": discovered,
                    }
                },
                "all_families_full": discovered > 0,
            }
        ),
        encoding="utf-8",
    )


def test_post_completion_memory_refuse_un_job_non_finalise_sur_disque(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab_root = tmp_path / "lab"
    workspace = lab_root / "workspace"
    result_dir = lab_root / "results"
    workspace.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    result = _result(workspace)
    result["analysis_complete"] = True
    result["completion_recorded"] = True
    result_path = result_dir / "JOB_RESULT.json"
    on_disk = dict(result)
    on_disk["completion_recorded"] = False
    result_path.write_text(json.dumps(on_disk), encoding="utf-8")

    monkeypatch.setattr(
        family_economic_job,
        "record_family_economic_memory",
        lambda **kwargs: pytest.fail("memory must not run before durable completion"),
    )

    with pytest.raises(
        autonomous_completion.AutonomousCompletionError,
        match="JOB_RESULT disque non finalisé",
    ):
        autonomous_completion._persist_post_completion_economic_memory(
            result=result,
            result_path=result_path,
            lab_root=lab_root,
        )


def test_finalize_persiste_completion_avant_memoire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    lab_root = tmp_path / "lab"
    workspace = lab_root / "workspace"
    result_dir = lab_root / "results"
    workspace.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    _write_economic_reports(workspace)
    request_path = result_dir / "request.json"
    result_path = result_dir / "JOB_RESULT.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")
    result_path.write_text(json.dumps(_result(workspace)), encoding="utf-8")

    calls: list[str] = []

    def fake_registry(*args, **kwargs):
        calls.append("registry")
        path = lab_root / "runtime/reports/autonomous_research/COMPLETED_SUITES.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
        return path

    def fake_memory(**kwargs):
        on_disk = json.loads(result_path.read_text(encoding="utf-8"))
        assert on_disk["analysis_complete"] is True
        assert on_disk["completion_recorded"] is True
        calls.append("memory")
        return {"key": "certified-proof-key"}

    monkeypatch.setattr(autonomous_completion, "record_completed_suite", fake_registry)
    monkeypatch.setattr(family_economic_job, "record_family_economic_memory", fake_memory)

    contract = autonomous_completion.finalize_autonomous_completion(
        request_path=request_path,
        project_root=project_root,
        lab_root=lab_root,
        result_dir=result_dir,
    )

    assert calls == ["registry", "memory"]
    assert contract["completion_recorded"] is True
    assert contract["economic_memory_status"] == "CERTIFIED_RECORDED"
    assert contract["economic_memory_key"] == "certified-proof-key"
    final = json.loads(result_path.read_text(encoding="utf-8"))
    assert final["completion_recorded"] is True
    assert final["economic_memory_status"] == "CERTIFIED_RECORDED"
    assert final["economic_memory_key"] == "certified-proof-key"


def test_incomplete_family_job_ne_touche_jamais_la_memoire(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "project"
    lab_root = tmp_path / "lab"
    workspace = lab_root / "workspace"
    result_dir = lab_root / "results"
    workspace.mkdir(parents=True)
    result_dir.mkdir(parents=True)
    _write_economic_reports(workspace, discovered=0)
    request_path = result_dir / "request.json"
    result_path = result_dir / "JOB_RESULT.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")
    result_path.write_text(json.dumps(_result(workspace)), encoding="utf-8")

    monkeypatch.setattr(
        family_economic_job,
        "record_family_economic_memory",
        lambda **kwargs: pytest.fail("memory must not run for incomplete analysis"),
    )

    with pytest.raises(autonomous_completion.AutonomousCompletionError):
        autonomous_completion.finalize_autonomous_completion(
            request_path=request_path,
            project_root=project_root,
            lab_root=lab_root,
            result_dir=result_dir,
        )

    final = json.loads(result_path.read_text(encoding="utf-8"))
    assert final["status"] == "NO_GO"
    assert final["analysis_complete"] is False
    assert final["completion_recorded"] is False
