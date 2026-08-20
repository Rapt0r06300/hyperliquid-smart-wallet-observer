from __future__ import annotations

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
