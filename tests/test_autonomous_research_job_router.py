from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.ops import autonomous_research_job as canonical_job
from hl_observer.ops import autonomous_research_job_router as router


def _request(suite: str) -> dict[str, object]:
    return {
        "schema": canonical_job.SCHEMA,
        "job_id": "router-test",
        "suite": suite,
        "mode": "economic",
        "project_ref": "main",
        "project_sha": "a" * 40,
        "release_id": canonical_job.CANONICAL_RELEASE_ID,
        "dataset_repository": canonical_job.CANONICAL_DATASET_REPOSITORY,
        "paper_only": True,
        "real_execution": False,
        "start_live_collection": False,
        "download": True,
        "max_download_gib": 20.0,
        "stage_timeout_seconds": 3600,
        "cross_budget_s": 20.0,
        "lead_history_sources": 8,
    }


def test_canonical_worker_stays_narrow() -> None:
    before = set(canonical_job.ECONOMIC_SUITES)
    with pytest.raises(ValueError, match="mode economic"):
        canonical_job.validate_request(_request("copy-vault-full"))
    assert set(canonical_job.ECONOMIC_SUITES) == before


@pytest.mark.parametrize(
    "suite",
    ["copy-vault-full", "lead-lag-full", "cross-venue-full"],
)
def test_router_accepts_only_active_family_economic_suites(suite: str) -> None:
    before = set(canonical_job.ECONOMIC_SUITES)
    validated = router.validate_request(_request(suite))
    assert validated["suite"] == suite
    assert validated["mode"] == "economic"
    assert set(canonical_job.ECONOMIC_SUITES) == before


def test_router_does_not_turn_unrelated_archives_into_economic_jobs() -> None:
    before = set(canonical_job.ECONOMIC_SUITES)
    with pytest.raises(ValueError, match="mode economic"):
        router.validate_request(_request("sqlite-all-safe"))
    assert set(canonical_job.ECONOMIC_SUITES) == before


def test_allowed_economic_suites_is_union_without_mutation() -> None:
    canonical_before = set(canonical_job.ECONOMIC_SUITES)
    family_before = set(router.FAMILY_ECONOMIC_SUITES)
    assert router.allowed_economic_suites() == frozenset(canonical_before | family_before)
    assert set(canonical_job.ECONOMIC_SUITES) == canonical_before
    assert set(router.FAMILY_ECONOMIC_SUITES) == family_before


def test_print_lead_lag_diagnostic_is_fail_closed_on_malformed_events(capsys) -> None:
    router._print_lead_lag_diagnostic({"causal_book_availability": "bad"})
    first = capsys.readouterr().out
    assert "LEAD_LAG_CAUSAL_GAP_DIAGNOSTIC" in first
    assert "events=None" in first

    router._print_lead_lag_diagnostic(
        {
            "diagnostic_threshold_bps": 8,
            "economic_threshold_bps": 20,
            "economic_parameters_modified": False,
            "causal_book_availability": {
                "event_count": 2,
                "root_cause": "book_gap",
                "classification_counts": {"fresh": 1},
                "events": ["bad", {"event_ts_ms": 123, "classification": "fresh"}],
            },
        }
    )
    second = capsys.readouterr().out
    assert 'counts={"fresh": 1}' in second
    assert "LEAD_LAG_CAUSAL_GAP_EVENT index=2 ts_ms=123 class=fresh" in second


def test_family_postprocessing_noops_for_other_suites(tmp_path: Path) -> None:
    router._run_family_postprocessing(suite="copy-vault-full", result_dir=tmp_path)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"status": "FAILED"}, "requires successful family pipeline"),
        ({"status": "SUCCESS"}, "has no workspace"),
    ],
)
def test_family_postprocessing_rejects_invalid_result_payload(
    tmp_path: Path, payload: dict[str, object], message: str
) -> None:
    (tmp_path / "JOB_RESULT.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match=message):
        router._run_family_postprocessing(suite="lead-lag-full", result_dir=tmp_path)


def test_family_postprocessing_requires_result_and_workspace(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="result missing"):
        router._run_family_postprocessing(suite="lead-lag-full", result_dir=tmp_path)

    missing = tmp_path / "missing-workspace"
    (tmp_path / "JOB_RESULT.json").write_text(
        json.dumps({"status": "SUCCESS", "workspace": str(missing)}), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="workspace missing"):
        router._run_family_postprocessing(suite="lead-lag-full", result_dir=tmp_path)


def test_family_postprocessing_writes_diagnostic_without_raw_data(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (tmp_path / "JOB_RESULT.json").write_text(
        json.dumps({"status": "SUCCESS", "workspace": str(workspace)}), encoding="utf-8"
    )
    calls = []

    def fake_writer(actual_workspace, *, output_dir):
        calls.append((actual_workspace, output_dir))
        return (
            output_dir / "lead-lag.json",
            output_dir / "lead-lag.md",
            {"causal_book_availability": {"events": []}},
        )

    monkeypatch.setattr(router, "write_lead_lag_causal_gap_diagnostic", fake_writer)
    router._run_family_postprocessing(suite="lead-lag-full", result_dir=tmp_path)

    assert calls == [(workspace.resolve(), tmp_path)]
    out = capsys.readouterr().out
    assert "LEAD_LAG_CAUSAL_GAP_FILES json=lead-lag.json markdown=lead-lag.md raw_data_uploaded=False" in out


def _main_args(tmp_path: Path) -> list[str]:
    return [
        "--request", str(tmp_path / "request.json"),
        "--project-root", str(tmp_path / "project"),
        "--lab-root", str(tmp_path / "lab"),
        "--result-dir", str(tmp_path / "result"),
    ]


def test_main_routes_family_success_and_postprocessing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(canonical_job, "_load_request", lambda _path: {"mode": "economic", "suite": "lead-lag-full"})
    monkeypatch.setattr(router, "execute_family_job", lambda *args, **kwargs: 0)
    seen = []
    monkeypatch.setattr(router, "_run_family_postprocessing", lambda **kwargs: seen.append(kwargs))
    assert router.main(_main_args(tmp_path)) == 0
    assert seen == [{"suite": "lead-lag-full", "result_dir": (tmp_path / "result").resolve()}]


def test_main_skips_postprocessing_after_family_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(canonical_job, "_load_request", lambda _path: {"mode": "economic", "suite": "copy-vault-full"})
    monkeypatch.setattr(router, "execute_family_job", lambda *args, **kwargs: 7)
    monkeypatch.setattr(router, "_run_family_postprocessing", lambda **kwargs: pytest.fail("must not postprocess failed family job"))
    assert router.main(_main_args(tmp_path)) == 7


def test_main_delegates_non_family_request_to_canonical_job(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(canonical_job, "_load_request", lambda _path: {"mode": "archive", "suite": "sqlite-all-safe"})
    monkeypatch.setattr(canonical_job, "execute_job", lambda *args, **kwargs: 9)
    assert router.main(_main_args(tmp_path)) == 9


def test_main_converts_expected_failures_to_no_go(tmp_path: Path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(canonical_job, "_load_request", lambda _path: (_ for _ in ()).throw(ValueError("bad request")))
    assert router.main(_main_args(tmp_path)) == 20
    assert "ALINA_AUTONOMOUS_RESEARCH_ROUTER_NO_GO: ValueError: bad request" in capsys.readouterr().out
