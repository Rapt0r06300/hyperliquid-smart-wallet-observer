from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import hl_observer.datasets.max_data_router as router


def test_route_decision_family_and_canonical() -> None:
    family_suite = next(iter(router.FAMILY_ECONOMIC_SUITES))
    row = router.route_decision({
        "status": "READY",
        "recommended_suite": family_suite,
        "recommended_mode": "historical-deep",
    })
    assert row["recommended_mode"] == "economic"
    assert row["execution_route"] == "ACTIVE_FAMILY_FULL_COLD_ECONOMIC_ADAPTER"
    assert row["routing_changed_only_mode"] is True

    original = {"status": "NO_GO", "recommended_suite": None}
    row = router.route_decision(original)
    assert row["execution_route"] == "CANONICAL"
    assert row["routing_changed_only_mode"] is False
    assert original == {"status": "NO_GO", "recommended_suite": None}


def test_choose_delegates_then_routes(monkeypatch) -> None:
    family_suite = next(iter(router.FAMILY_ECONOMIC_SUITES))
    captured = {}

    def choose(**kwargs):
        captured.update(kwargs)
        return {
            "status": "READY",
            "recommended_suite": family_suite,
            "recommended_mode": "historical-deep",
        }

    monkeypatch.setattr(router.canonical_policy, "choose_max_data_job", choose)
    row = router.choose_max_data_job(
        family_decisions=[{"family": "copy_vault"}],
        suite_plans={"x": {}},
        completed_suites=["a"],
        free_disk_gib=50,
        all_targets_reached=False,
        reserve_gib=10,
    )
    assert row["recommended_mode"] == "economic"
    assert captured["free_disk_gib"] == 50
    assert captured["reserve_gib"] == 10


def test_main_ready_nogo_and_validation(tmp_path, monkeypatch, capsys) -> None:
    brain = tmp_path / "brain.json"
    brain.write_text(json.dumps({"family_decisions": [{"family": "copy_vault"}]}), encoding="utf-8")
    lab = tmp_path / "lab"
    lab.mkdir()
    out = tmp_path / "out"
    monkeypatch.setattr(router.canonical_policy, "load_suite_plans", lambda root: {"economic-full": {}})
    monkeypatch.setattr(router.canonical_policy, "completed_suites_from_registry", lambda root, project_sha=None: ("persisted",))
    monkeypatch.setattr(router.canonical_policy, "targets_reached_from_brain", lambda decisions: False)
    monkeypatch.setattr(router.shutil, "disk_usage", lambda root: SimpleNamespace(free=100 * 1024**3))
    monkeypatch.setattr(router.canonical_policy, "completed_registry_path", lambda root: lab / "registry.json")
    written = {}

    def write_decision(output_dir, decision):
        written.update(decision)
        return out / "d.json", out / "d.md"

    monkeypatch.setattr(router.canonical_policy, "write_decision", write_decision)
    monkeypatch.setattr(router, "choose_max_data_job", lambda **kwargs: {
        "status": "READY",
        "recommended_suite": "economic-full",
        "recommended_mode": "economic",
    })
    assert router.main([
        "--brain-json", str(brain),
        "--lab-root", str(lab),
        "--output-dir", str(out),
        "--completed-suite", "manual",
        "--project-sha", "a" * 40,
    ]) == 0
    assert written["project_sha_scope"] == "a" * 40
    assert "ALINA_MAX_DATA status=READY" in capsys.readouterr().out

    monkeypatch.setattr(router, "choose_max_data_job", lambda **kwargs: {
        "status": "NO_GO",
        "recommended_suite": None,
        "recommended_mode": None,
    })
    assert router.main([
        "--brain-json", str(brain),
        "--lab-root", str(lab),
        "--output-dir", str(out),
    ]) == 4

    brain.write_text(json.dumps({"family_decisions": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="family_decisions absent"):
        router.main(["--brain-json", str(brain), "--lab-root", str(lab), "--output-dir", str(out)])

    brain.write_text(json.dumps({"family_decisions": []}), encoding="utf-8")
    monkeypatch.setattr(router.canonical_policy, "load_suite_plans", lambda root: {})
    with pytest.raises(ValueError, match="BIBLIOTHEQUE_180GO"):
        router.main(["--brain-json", str(brain), "--lab-root", str(lab), "--output-dir", str(out)])
