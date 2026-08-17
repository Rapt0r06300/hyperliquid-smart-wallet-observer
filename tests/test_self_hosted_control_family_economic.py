from __future__ import annotations

import pytest

from hl_observer.ops.self_hosted_control import build_control_bundle

SHA = "b" * 40


def _control(suite: str, mode: str = "economic") -> dict[str, object]:
    return {
        "schema": "alina.self_hosted_control.v1",
        "job_id": "family-economic-route",
        "suite": suite,
        "mode": mode,
        "download": True,
        "max_download_gib": 20.0,
        "stage_timeout_seconds": 3600,
        "cross_budget_s": 20.0,
        "lead_history_sources": 8,
        "force": False,
        "max_cycle_seconds": 3600,
    }


@pytest.mark.parametrize(
    "suite",
    ["copy-vault-full", "lead-lag-full", "cross-venue-full"],
)
def test_control_accepts_active_family_economic_route_without_weakening_safety(suite: str) -> None:
    bundle = build_control_bundle(_control(suite), project_sha=SHA)
    worker = bundle["worker_request"]
    assert worker["suite"] == suite
    assert worker["mode"] == "economic"
    assert worker["project_ref"] == "main"
    assert worker["project_sha"] == SHA
    assert worker["paper_only"] is True
    assert worker["real_execution"] is False
    assert worker["start_live_collection"] is False
    assert bundle["security"]["real_execution"] is False


def test_control_still_rejects_unrelated_economic_suite() -> None:
    with pytest.raises(ValueError, match="mode economic"):
        build_control_bundle(_control("sqlite-all-safe"), project_sha=SHA)
