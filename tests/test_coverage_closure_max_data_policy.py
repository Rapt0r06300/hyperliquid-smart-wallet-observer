from __future__ import annotations

import json

import pytest

import hl_observer.datasets.max_data_policy as policy


def test_number_sha_zero_ladder_and_target_helpers() -> None:
    assert policy._number(1) == 1.0
    assert policy._number(-1) is None
    assert policy._number("bad") is None
    assert policy._valid_sha("a" * 40) is True
    assert policy._valid_sha("g" * 40) is False
    assert policy._explicit_zero(0) is True
    assert policy._explicit_zero(False) is False
    assert policy._explicit_zero("0") is False
    assert policy._top_family([]) is None
    top = policy._top_family([
        {"family": "lead_lag", "priority": 1},
        {"family": "copy_vault", "priority": 2},
    ])
    assert top == "copy_vault"
    ladder = policy.suite_ladder("copy_vault")
    assert ladder[0] == "economic-full"
    assert "copy-vault-full" in ladder
    assert len(ladder) == len(set(ladder))

    families = [
        {"family": family, "phase": "FREEZE_AND_CONFIRM_FORWARD", "priority": 1}
        for family in policy.REQUIRED_FAMILIES
    ]
    assert policy.targets_reached_from_brain(families) is True
    assert policy.targets_reached_from_brain(families[:-1]) is False


def test_completed_registry_record_load_filter_and_fail_closed(tmp_path) -> None:
    empty = policy.load_completed_suite_registry(tmp_path)
    assert empty["schema"] == policy.COMPLETED_REGISTRY_SCHEMA
    assert empty["suites"] == {}
    assert empty["paper_only"] is True and empty["real_execution"] is False

    suite = policy.suite_names()[0]
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sha = "a" * 40
    path = policy.record_completed_suite(
        tmp_path,
        suite=suite,
        mode="historical-deep",
        job_id="job-1",
        project_sha=sha,
        workspace=workspace,
        completed_at_utc="2026-01-01T00:00:00+00:00",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["completed_suite_count"] == 1
    assert payload["history_count"] == 1
    assert policy.completed_suites_from_registry(tmp_path) == (suite,)
    assert policy.completed_suites_from_registry(tmp_path, project_sha=sha) == (suite,)
    with pytest.raises(ValueError, match="project_sha invalide"):
        policy.completed_suites_from_registry(tmp_path, project_sha="bad")

    payload["paper_only"] = False
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="paper/read-only"):
        policy.load_completed_suite_registry(tmp_path)


def test_record_validation_rejects_unknown_mode_job_sha_and_outside_workspace(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    suite = policy.suite_names()[0]
    common = {
        "lab_root": tmp_path,
        "suite": suite,
        "mode": "economic",
        "job_id": "j",
        "project_sha": "a" * 40,
        "workspace": workspace,
    }
    with pytest.raises(ValueError, match="Suite inconnue"):
        policy.record_completed_suite(**{**common, "suite": "bad"})
    with pytest.raises(ValueError, match="Mode non analysant"):
        policy.record_completed_suite(**{**common, "mode": "prepare"})
    with pytest.raises(ValueError, match="job_id"):
        policy.record_completed_suite(**{**common, "job_id": ""})
    with pytest.raises(ValueError, match="project_sha invalide"):
        policy.record_completed_suite(**{**common, "project_sha": "bad"})
    outside = tmp_path.parent / "outside-workspace"
    outside.mkdir(exist_ok=True)
    with pytest.raises(ValueError, match="hors du laboratoire"):
        policy.record_completed_suite(**{**common, "workspace": outside})


def test_choose_stop_ready_and_nogo_contract() -> None:
    families = [
        {"family": family, "phase": "FREEZE_AND_CONFIRM_FORWARD", "priority": 1}
        for family in policy.REQUIRED_FAMILIES
    ]
    stop = policy.choose_max_data_job(
        family_decisions=families,
        suite_plans={},
        completed_suites=(),
        free_disk_gib=100,
        all_targets_reached=True,
    )
    assert stop["status"] == "STOP_PROOF_REACHED"
    assert stop["download_budget_gib"] == 0.0
    assert stop["target_contract"]["target_net_usd_per_family"] == 4.0
    assert stop["target_contract"]["independent_targets_required"] is True
    assert stop["target_contract"]["aggregate_substitution_allowed"] is False
    assert stop["holdout_used_for_ranking"] is False

    ready = policy.choose_max_data_job(
        family_decisions=[{"family": "copy_vault", "priority": 9}],
        suite_plans={
            "economic-full": {
                "missing_asset_count": 0,
                "remaining_download_gib": 2.0,
            }
        },
        completed_suites=(),
        free_disk_gib=100,
        all_targets_reached=False,
        reserve_gib=25,
    )
    assert ready["status"] == "READY"
    assert ready["recommended_suite"] == "economic-full"
    assert ready["recommended_mode"] == "economic"
    assert ready["download_budget_gib"] > 0
    assert ready["holdout_used_for_ranking"] is False

    no_go = policy.choose_max_data_job(
        family_decisions=[],
        suite_plans={},
        completed_suites=(),
        free_disk_gib=1,
        all_targets_reached=False,
        reserve_gib=1,
    )
    assert no_go["status"] == "NO_GO"
    assert no_go["recommended_suite"] is None
    assert no_go["paper_read_only"] is True and no_go["real_execution"] is False


def test_choose_rejections_and_invalid_numbers() -> None:
    with pytest.raises(ValueError, match="nombres positifs"):
        policy.choose_max_data_job(
            family_decisions=[],
            suite_plans={},
            free_disk_gib=-1,
            all_targets_reached=False,
        )

    plans = {
        "economic-full": {"missing_asset_count": 1, "remaining_download_gib": 1},
        "microstructure-full": {"missing_asset_count": 0, "remaining_download_gib": 100},
    }
    row = policy.choose_max_data_job(
        family_decisions=[],
        suite_plans=plans,
        completed_suites=("research-lab-full",),
        free_disk_gib=10,
        all_targets_reached=False,
        reserve_gib=5,
    )
    assert row["status"] == "NO_GO"
    reasons = {item["reason"] for item in row["rejected"]}
    assert "RELEASE_ASSETS_MISSING" in reasons
    assert "PLAN_MISSING" in reasons or "INSUFFICIENT_DISK" in reasons
