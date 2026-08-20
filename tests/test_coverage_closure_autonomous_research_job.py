from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import hl_observer.ops.autonomous_research_job as job


def _valid_request(**overrides):
    payload = {
        "schema": job.SCHEMA,
        "job_id": "coverage-job",
        "suite": "economic-full",
        "mode": "economic",
        "project_ref": "main",
        "project_sha": "a" * 40,
        "release_id": job.CANONICAL_RELEASE_ID,
        "dataset_repository": job.CANONICAL_DATASET_REPOSITORY,
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


def test_canonical_digest_load_and_validate_success(tmp_path) -> None:
    one = job.request_digest({"b": 2, "a": 1})
    two = job.request_digest({"a": 1, "b": 2})
    assert one == two and len(one) == 64
    path = tmp_path / "request.json"
    path.write_text(json.dumps(_valid_request()), encoding="utf-8")
    loaded = job._load_request(path)
    validated = job.validate_request(loaded)
    assert validated["job_id"] == "coverage-job"
    assert validated["suite"] == "economic-full"
    assert validated["paper_only"] is True
    assert validated["real_execution"] is False
    assert validated["start_live_collection"] is False
    assert validated["project_ref"] == "main"


def test_request_load_and_validation_fail_closed(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="objet JSON"):
        job._load_request(path)
    path.write_text("bad", encoding="utf-8")
    with pytest.raises(ValueError, match="Requête illisible"):
        job._load_request(path)

    cases = [
        ({"schema": "bad"}, "schema"),
        ({"job_id": "!"}, "job_id"),
        ({"suite": "bad"}, "suite inconnue"),
        ({"mode": "bad"}, "mode inconnu"),
        ({"mode": "economic", "suite": "full-archive"}, "economic exige"),
        ({"project_sha": "bad"}, "project_sha"),
        ({"project_ref": "dev"}, "branche main"),
        ({"release_id": 1}, "release_id"),
        ({"dataset_repository": "other/repo"}, "dataset_repository"),
        ({"paper_only": False}, "paper_only"),
        ({"real_execution": True}, "real_execution"),
        ({"start_live_collection": True}, "start_live_collection"),
        ({"max_download_gib": 0}, "max_download_gib"),
        ({"max_download_gib": 221}, "max_download_gib"),
        ({"stage_timeout_seconds": 59}, "stage_timeout_seconds"),
        ({"stage_timeout_seconds": 86401}, "stage_timeout_seconds"),
        ({"cross_budget_s": -1}, "cross_budget_s"),
        ({"cross_budget_s": 3601}, "cross_budget_s"),
        ({"lead_history_sources": -1}, "lead_history_sources"),
        ({"lead_history_sources": 100001}, "lead_history_sources"),
    ]
    for change, message in cases:
        with pytest.raises(ValueError, match=message):
            job.validate_request(_valid_request(**change))


def test_git_head_execution_guard_and_safe_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        job.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="B" * 40 + "\n", stderr=""),
    )
    assert job._git_head(tmp_path) == "b" * 40
    monkeypatch.setattr(
        job.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="bad"),
    )
    with pytest.raises(RuntimeError, match="Impossible de lire"):
        job._git_head(tmp_path)

    for key in ("HL_ENABLE_MAINNET_EXECUTION", "HL_ENABLE_TESTNET_EXECUTION", "REAL_MAINNET_TRADING"):
        monkeypatch.delenv(key, raising=False)
    job._assert_execution_disabled()
    monkeypatch.setenv("HL_ENABLE_MAINNET_EXECUTION", "true")
    with pytest.raises(RuntimeError, match="activée"):
        job._assert_execution_disabled()
    env = job._safe_environment()
    assert env["HL_ENABLE_MAINNET_EXECUTION"] == "0"
    assert env["HL_ENABLE_TESTNET_EXECUTION"] == "0"
    assert env["REAL_MAINNET_TRADING"] == "false"
    assert env["HYPERSMART_ANALYSIS_LOCAL_ONLY"] == "1"


def test_copy_if_small_collect_reports_and_write_result(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.md"
    source.write_text("hello", encoding="utf-8")
    copied = []
    destination = tmp_path / "reports"
    job._copy_if_small(source, destination, copied)
    assert len(copied) == 1 and (destination / "source.md").read_text(encoding="utf-8") == "hello"
    job._copy_if_small(source, destination, copied)
    assert len(copied) == 2
    assert len(list(destination.glob("source*.md"))) == 2

    huge = tmp_path / "huge.bin"
    huge.write_bytes(b"x")
    monkeypatch.setattr(job, "MAX_SMALL_REPORT_BYTES", 0)
    before = len(copied)
    job._copy_if_small(huge, destination, copied)
    assert len(copied) == before

    payload = {
        "job_id": "j",
        "status": "SUCCESS",
        "suite": "economic-full",
        "mode": "economic",
        "project_sha": "a" * 40,
        "request_digest": "d" * 64,
        "workspace": str(tmp_path),
        "steps": [{"name": "s", "return_code": 0, "duration_seconds": 1, "timed_out": False}],
        "copied_reports": copied,
    }
    json_path, md_path = job._write_result(tmp_path / "result", payload)
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "SUCCESS"
    text = md_path.read_text(encoding="utf-8")
    assert "SUCCESS" in text and "Exécution réelle : **NON**" in text
    assert "ne signifie pas PnL positif" in text
