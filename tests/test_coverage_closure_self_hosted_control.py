from __future__ import annotations

import json

import pytest

from hl_observer.ops import self_hosted_control as control


SHA = "a" * 40


def _raw(**overrides):
    value = {
        "schema": control.CONTROL_SCHEMA,
        "job_id": "final-1",
        "suite": "unit-suite",
        "mode": "unit-mode",
    }
    value.update(overrides)
    return value


def test_load_json_success_and_all_failures(tmp_path) -> None:
    path = tmp_path / "control.json"
    path.write_text(json.dumps(_raw()), encoding="utf-8")
    assert control._load_json(path)["job_id"] == "final-1"

    with pytest.raises(ValueError, match="Commande illisible"):
        control._load_json(tmp_path / "missing.json")

    path.write_text("{", encoding="utf-8")
    with pytest.raises(ValueError, match="Commande illisible"):
        control._load_json(path)

    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="objet JSON"):
        control._load_json(path)


def test_strict_bool_defaults_accepts_bool_and_rejects_other_types() -> None:
    assert control._strict_bool({}, "x", True) is True
    assert control._strict_bool({"x": False}, "x", True) is False
    with pytest.raises(ValueError, match="booléen JSON"):
        control._strict_bool({"x": 1}, "x", True)


def test_normalize_control_defaults_bounds_and_truncation() -> None:
    normalized = control.normalize_control(_raw())
    assert normalized["download"] is True
    assert normalized["force"] is False
    assert normalized["max_cycle_seconds"] == control.MAX_CYCLE_SECONDS
    assert normalized["max_download_gib"] == 20.0
    assert normalized["stage_timeout_seconds"] == 3600
    assert normalized["cross_budget_s"] == 20.0
    assert normalized["lead_history_sources"] == 8
    assert normalized["requested_by"] == "GitHub"
    assert normalized["note"] == ""

    long_requested = "R" * 200
    long_note = "N" * 700
    normalized = control.normalize_control(
        _raw(
            requested_by=long_requested,
            note=long_note,
            max_cycle_seconds=60,
            download=False,
            force=True,
            max_download_gib="4.5",
            stage_timeout_seconds="120",
            cross_budget_s="2.5",
            lead_history_sources="3",
        )
    )
    assert len(normalized["requested_by"]) == 120
    assert len(normalized["note"]) == 500
    assert normalized["download"] is False
    assert normalized["force"] is True
    assert normalized["max_download_gib"] == 4.5
    assert normalized["stage_timeout_seconds"] == 120
    assert normalized["cross_budget_s"] == 2.5
    assert normalized["lead_history_sources"] == 3


def test_normalize_control_rejects_schema_job_and_cycle_bounds() -> None:
    with pytest.raises(ValueError, match="schema"):
        control.normalize_control({"schema": "bad", "job_id": "x"})
    for bad in ("", " space", "*bad", "a" * 81):
        with pytest.raises(ValueError, match="job_id invalide"):
            control.normalize_control(_raw(job_id=bad))
    with pytest.raises(ValueError, match="max_cycle_seconds"):
        control.normalize_control(_raw(max_cycle_seconds=59))
    with pytest.raises(ValueError, match="max_cycle_seconds"):
        control.normalize_control(_raw(max_cycle_seconds=control.MAX_CYCLE_SECONDS + 1))
    with pytest.raises(ValueError, match="booléen JSON"):
        control.normalize_control(_raw(download="yes"))
    with pytest.raises(ValueError, match="booléen JSON"):
        control.normalize_control(_raw(force=1))


def test_build_worker_request_forces_canonical_security(monkeypatch) -> None:
    monkeypatch.setattr(control, "validate_request", lambda value: value)
    worker = control.build_worker_request(
        _raw(
            download=False,
            max_download_gib=3,
            stage_timeout_seconds=90,
            cross_budget_s=4,
            lead_history_sources=2,
        ),
        project_sha=SHA.upper(),
    )
    assert worker["project_ref"] == "main"
    assert worker["project_sha"] == SHA
    assert worker["release_id"] == control.CANONICAL_RELEASE_ID
    assert worker["dataset_repository"] == control.CANONICAL_DATASET_REPOSITORY
    assert worker["paper_only"] is True
    assert worker["real_execution"] is False
    assert worker["start_live_collection"] is False
    assert worker["download"] is False
    assert worker["max_download_gib"] == 3.0
    assert worker["stage_timeout_seconds"] == 90
    assert worker["cross_budget_s"] == 4.0
    assert worker["lead_history_sources"] == 2

    for bad_sha in ("", "abc", "g" * 40, "a" * 39, "a" * 41):
        with pytest.raises(ValueError, match="SHA Git complet"):
            control.build_worker_request(_raw(), project_sha=bad_sha)


def test_build_control_bundle_reuses_normalized_guard_and_security(monkeypatch) -> None:
    monkeypatch.setattr(control, "validate_request", lambda value: value)
    bundle = control.build_control_bundle(_raw(force=True, max_cycle_seconds=120), project_sha=SHA.upper())
    assert bundle["schema"] == "alina.self_hosted_control_bundle.v1"
    assert bundle["control"]["job_id"] == "final-1"
    assert bundle["guard"] == {"max_cycle_seconds": 120, "force": True}
    assert bundle["security"] == {
        "paper_only": True,
        "real_execution": False,
        "live_collection": False,
        "project_ref": "main",
        "project_sha": SHA,
    }
    assert bundle["worker_request"]["project_sha"] == SHA


def test_main_writes_worker_and_optional_bundle(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(control, "validate_request", lambda value: value)
    control_path = tmp_path / "control.json"
    worker_path = tmp_path / "nested" / "worker.json"
    bundle_path = tmp_path / "bundle" / "bundle.json"
    control_path.write_text(json.dumps(_raw(max_cycle_seconds=180)), encoding="utf-8")

    assert control.main([
        "--control", str(control_path),
        "--project-sha", SHA,
        "--worker-request", str(worker_path),
        "--bundle-output", str(bundle_path),
    ]) == 0
    worker = json.loads(worker_path.read_text(encoding="utf-8"))
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert worker["project_ref"] == "main"
    assert worker["paper_only"] is True
    assert bundle["security"]["real_execution"] is False
    out = capsys.readouterr().out
    assert "ALINA_SELF_HOSTED_CONTROL_READY" in out
    assert "max_cycle=180s" in out


def test_main_without_bundle_output(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setattr(control, "validate_request", lambda value: value)
    control_path = tmp_path / "control.json"
    worker_path = tmp_path / "worker.json"
    control_path.write_text(json.dumps(_raw()), encoding="utf-8")
    assert control.main([
        "--control", str(control_path),
        "--project-sha", SHA,
        "--worker-request", str(worker_path),
    ]) == 0
    assert worker_path.exists()
    assert "job=final-1" in capsys.readouterr().out
