from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.ops import autonomous_research_job as worker


SHA = "a" * 40


def _request(**overrides):
    payload = {
        "schema": worker.SCHEMA,
        "job_id": "job-test-001",
        "suite": "economic-full",
        "mode": "economic",
        "project_ref": "main",
        "project_sha": SHA,
        "release_id": worker.CANONICAL_RELEASE_ID,
        "dataset_repository": worker.CANONICAL_DATASET_REPOSITORY,
        "paper_only": True,
        "real_execution": False,
        "start_live_collection": False,
        "download": True,
        "max_download_gib": 20,
        "stage_timeout_seconds": 3600,
        "cross_budget_s": 20,
        "lead_history_sources": 8,
    }
    payload.update(overrides)
    return payload


def test_validation_refuse_execution_reelle_collecte_live_et_autre_branche() -> None:
    for payload in (
        _request(real_execution=True),
        _request(paper_only=False),
        _request(start_live_collection=True),
        _request(project_ref="feature/test"),
    ):
        with pytest.raises(ValueError):
            worker.validate_request(payload)


def test_validation_refuse_sha_suite_et_plafond_de_telechargement_invalides() -> None:
    for payload in (
        _request(project_sha="abc"),
        _request(suite="inconnue"),
        _request(max_download_gib=0),
        _request(max_download_gib=221),
    ):
        with pytest.raises(ValueError):
            worker.validate_request(payload)


def test_mode_economique_reste_limite_aux_suites_economiques() -> None:
    with pytest.raises(ValueError):
        worker.validate_request(_request(suite="research-lab-full", mode="economic"))


def test_digest_requete_est_reproductible() -> None:
    first = worker.validate_request(_request())
    second = worker.validate_request(dict(reversed(list(_request().items()))))
    assert worker.request_digest(first) == worker.request_digest(second)


def test_worker_economique_prepare_workspace_et_interdit_collecte_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    lab = tmp_path / "lab"
    workspace = lab / "data" / "hypersmart_datasets" / "workspaces" / "economic-full" / "1234567890abcdef"
    (workspace / "runtime" / "data").mkdir(parents=True)
    result_dir = tmp_path / "result"
    request_file = tmp_path / "job.json"
    request_file.write_text(json.dumps(_request()), encoding="utf-8")

    commands: list[list[str]] = []

    monkeypatch.setattr(worker, "_git_head", lambda _root: SHA)
    monkeypatch.setattr(worker, "_assert_execution_disabled", lambda: None)
    monkeypatch.setattr(worker, "resolve_current_workspace", lambda _root, _suite: workspace)
    monkeypatch.setattr(worker, "prepare_replay_workspace", lambda *args, **kwargs: {"status": "READY"})
    monkeypatch.setattr(worker, "_collect_small_reports", lambda *args, **kwargs: [])

    def fake_run(name, command, **kwargs):
        commands.append(list(command))
        return {
            "name": name,
            "return_code": 0,
            "timed_out": False,
            "duration_seconds": 0.01,
            "log_path": str(tmp_path / f"{name}.log"),
            "command": command,
        }

    monkeypatch.setattr(worker, "_run_logged", fake_run)

    rc = worker.execute_job(
        request_file,
        project_root=project,
        lab_root=lab,
        result_dir=result_dir,
    )
    assert rc == 0
    assert len(commands) == 3
    assert "dataset_bridge" in " ".join(commands[0])
    assert str(lab.resolve()) in commands[0]
    economic = " ".join(commands[1])
    assert "run_dataset_economic_campaigns.py" in economic
    assert "--no-start-collection" in economic
    assert "dataset_connection_audit" in " ".join(commands[2])

    payload = json.loads((result_dir / "JOB_RESULT.json").read_text(encoding="utf-8"))
    assert payload["status"] == "SUCCESS"
    assert payload["paper_only"] is True
    assert payload["real_execution"] is False
    assert payload["start_live_collection"] is False
    assert payload["project_sha"] == SHA


def test_worker_refuse_checkout_different_du_sha_demande(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    request_file = tmp_path / "job.json"
    request_file.write_text(json.dumps(_request()), encoding="utf-8")
    monkeypatch.setattr(worker, "_git_head", lambda _root: "b" * 40)
    monkeypatch.setattr(worker, "_assert_execution_disabled", lambda: None)

    with pytest.raises(RuntimeError, match="SHA projet différent"):
        worker.execute_job(
            request_file,
            project_root=project,
            lab_root=tmp_path / "lab",
            result_dir=tmp_path / "result",
        )


def test_worker_ne_relance_pas_un_job_success_identique(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    request_file = tmp_path / "job.json"
    request = worker.validate_request(_request())
    request_file.write_text(json.dumps(_request()), encoding="utf-8")
    result_dir = tmp_path / "result"
    result_dir.mkdir()
    (result_dir / "JOB_RESULT.json").write_text(
        json.dumps({"request_digest": worker.request_digest(request), "status": "SUCCESS"}),
        encoding="utf-8",
    )

    monkeypatch.setattr(worker, "_git_head", lambda _root: (_ for _ in ()).throw(AssertionError("ne doit pas relancer")))
    rc = worker.execute_job(
        request_file,
        project_root=project,
        lab_root=tmp_path / "lab",
        result_dir=result_dir,
    )
    assert rc == 0
