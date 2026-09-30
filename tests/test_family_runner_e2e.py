from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.ops import autonomous_completion
from hl_observer.ops import family_economic_job
from hl_observer.ops import self_hosted_control
from hl_observer.ops import self_hosted_return


SHA = "a" * 40
SUITE_COVERAGE_FAMILY = {
    "copy-vault-full": "copy_vault",
    "lead-lag-full": "lead_lag",
    "cross-venue-full": "cross_venue",
}


def _control(suite: str, **overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "schema": self_hosted_control.CONTROL_SCHEMA,
        "job_id": f"e2e-{suite}",
        "suite": suite,
        "mode": "economic",
        "download": False,
        "max_download_gib": 20.0,
        "stage_timeout_seconds": 3600,
        "cross_budget_s": 20.0,
        "lead_history_sources": 8,
        "force": False,
    }
    raw.update(overrides)
    return raw


def _write_completion_evidence(workspace: Path, suite: str) -> None:
    campaign_dir = workspace / "runtime" / "reports" / "economic_campaigns"
    datasets_dir = workspace / "runtime" / "reports" / "datasets"
    campaign_dir.mkdir(parents=True, exist_ok=True)
    datasets_dir.mkdir(parents=True, exist_ok=True)
    (campaign_dir / "HYPERSMART_ECONOMIC_OBJECTIVE_CAMPAIGN.md").write_text(
        "# deterministic E2E evidence\n", encoding="utf-8"
    )
    (datasets_dir / "DATASET_CONNECTION_AUDIT.json").write_text(
        json.dumps({"status": "PASS"}), encoding="utf-8"
    )
    family = SUITE_COVERAGE_FAMILY[suite]
    (datasets_dir / "SOURCE_CONSUMPTION_COVERAGE.json").write_text(
        json.dumps(
            {
                "all_families_full": False,
                "families": {
                    family: {"status": "FULL", "discovered_files": 1},
                },
            }
        ),
        encoding="utf-8",
    )
    # A compact campaign is enough to make ALINA_RETURN exercise its
    # certification gate. Canonical economic-proof semantics are covered by
    # test_self_hosted_return_canonical.py; this test owns orchestration wiring.
    campaign_family = family if family != "cross_venue" else "cross_venue_dislocation_v2"
    (campaign_dir / f"{campaign_family}.json").write_text(
        json.dumps({"family": campaign_family, "objective_status": "NON_ATTEINT"}),
        encoding="utf-8",
    )


def _fake_run_logged(name: str, *_args: object, **_kwargs: object) -> dict[str, object]:
    return {"name": name, "return_code": 0}


@pytest.mark.parametrize(
    "suite,expected_steps",
    [
        ("copy-vault-full", ["02_economic_campaigns", "04_connection_audit"]),
        (
            "lead-lag-full",
            ["02_economic_campaigns", "03_lead_lag_causal_audit", "04_connection_audit"],
        ),
        ("cross-venue-full", ["02_economic_campaigns", "04_connection_audit"]),
    ],
)
def test_family_runner_control_to_alina_return_is_exact_sha_paper_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    suite: str,
    expected_steps: list[str],
) -> None:
    project_root = tmp_path / "project"
    lab_root = tmp_path / "lab"
    workspace = lab_root / "workspace" / suite
    result_dir = tmp_path / "result"
    project_root.mkdir()
    workspace.mkdir(parents=True)
    _write_completion_evidence(workspace, suite)

    bundle = self_hosted_control.build_control_bundle(_control(suite), project_sha=SHA)
    request = bundle["worker_request"]
    assert bundle["security"] == {
        "paper_only": True,
        "real_execution": False,
        "live_collection": False,
        "project_ref": "main",
        "project_sha": SHA,
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")

    monkeypatch.setattr(family_economic_job.canonical_job, "_git_head", lambda _root: SHA)
    monkeypatch.setattr(family_economic_job, "resolve_current_workspace", lambda _root, _suite: workspace)
    monkeypatch.setattr(family_economic_job, "prepare_replay_workspace", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(family_economic_job.canonical_job, "_run_logged", _fake_run_logged)
    monkeypatch.setattr(family_economic_job.canonical_job, "_collect_small_reports", lambda *_args, **_kwargs: [])

    assert family_economic_job.execute_family_job(
        request_path,
        project_root=project_root,
        lab_root=lab_root,
        result_dir=result_dir,
    ) == 0
    before_completion = json.loads((result_dir / "JOB_RESULT.json").read_text(encoding="utf-8"))
    assert before_completion["project_sha"] == SHA
    assert before_completion["paper_only"] is True
    assert before_completion["real_execution"] is False
    assert before_completion["start_live_collection"] is False
    assert before_completion["analysis_complete"] is False
    assert [row["name"] for row in before_completion["steps"]] == expected_steps

    # Completion itself is real. Only the derived economic-memory cache is
    # stubbed because this E2E deliberately uses tiny non-economic fixtures.
    monkeypatch.setattr(
        autonomous_completion,
        "_persist_post_completion_economic_memory",
        lambda **_kwargs: ("TARGET_NOT_REACHED", None),
    )
    completion = autonomous_completion.finalize_autonomous_completion(
        request_path=request_path,
        project_root=project_root,
        lab_root=lab_root,
        result_dir=result_dir,
    )
    assert completion["analysis_complete"] is True
    assert completion["completion_recorded"] is True

    certification_calls: list[Path] = []

    def fake_certify(root: Path) -> dict[str, object]:
        certification_calls.append(Path(root))
        return {"all_families_certified": False, "families": {}}

    monkeypatch.setattr(self_hosted_return, "certify_workspace", fake_certify)
    monkeypatch.setattr(self_hosted_return, "build_decision", lambda _root: {})
    returned = self_hosted_return.build_return(result_dir)

    assert returned["technical_status"] == "SUCCESS"
    assert returned["completion_ready"] is True
    assert returned["project_sha"] == SHA
    assert returned["paper_only"] is True
    assert returned["real_execution"] is False
    assert returned["economic_certification"]["all_families_certified"] is False
    assert certification_calls == [workspace.resolve()]


def test_family_runner_refuse_stale_sha_avant_toute_etape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = self_hosted_control.build_worker_request(
        _control("copy-vault-full"), project_sha=SHA
    )
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request), encoding="utf-8")
    monkeypatch.setattr(family_economic_job.canonical_job, "_git_head", lambda _root: "b" * 40)
    monkeypatch.setattr(
        family_economic_job.canonical_job,
        "_run_logged",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("step executed on stale SHA")),
    )

    with pytest.raises(RuntimeError, match="SHA projet différent"):
        family_economic_job.execute_family_job(
            request_path,
            project_root=tmp_path / "project",
            lab_root=tmp_path / "lab",
            result_dir=tmp_path / "result",
        )


def test_control_refuse_branche_commande_et_execution_reelle() -> None:
    with pytest.raises(ValueError, match="schéma fermé"):
        self_hosted_control.build_control_bundle(
            _control("copy-vault-full", project_ref="feature"), project_sha=SHA
        )
    with pytest.raises(ValueError, match="schéma fermé"):
        self_hosted_control.build_control_bundle(
            _control("copy-vault-full", real_execution=True), project_sha=SHA
        )
