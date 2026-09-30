from __future__ import annotations

from hl_observer.datasets.max_data_router import choose_max_data_job, route_decision


def test_active_family_suite_is_routed_to_economic_mode() -> None:
    decision = route_decision(
        {
            "status": "READY",
            "recommended_suite": "copy-vault-full",
            "recommended_mode": "historical-deep",
        }
    )
    assert decision["recommended_mode"] == "economic"
    assert decision["execution_route"] == "ACTIVE_FAMILY_FULL_COLD_ECONOMIC_ADAPTER"
    assert decision["routing_changed_only_mode"] is True


def test_non_economic_archive_keeps_canonical_mode() -> None:
    decision = route_decision(
        {
            "status": "READY",
            "recommended_suite": "sqlite-all-safe",
            "recommended_mode": "historical-deep",
        }
    )
    assert decision["recommended_mode"] == "historical-deep"
    assert decision["execution_route"] == "CANONICAL"
    assert decision["routing_changed_only_mode"] is False


def test_router_does_not_change_stop_decision() -> None:
    decision = route_decision(
        {
            "status": "STOP_PROOF_REACHED",
            "recommended_suite": "lead-lag-full",
            "recommended_mode": None,
        }
    )
    assert decision["recommended_mode"] is None
    assert decision["execution_route"] == "CANONICAL"


def test_real_selector_routes_top_family_after_economic_full_completed() -> None:
    family_decisions = [
        {"family": "copy_vault", "priority": 100, "phase": "COLLECT_MORE"},
        {"family": "lead_lag", "priority": 50, "phase": "COLLECT_MORE"},
        {"family": "cross_venue_dislocation_v2", "priority": 40, "phase": "COLLECT_MORE"},
    ]
    suite_plans = {
        "copy-vault-full": {
            "missing_asset_count": 0,
            "remaining_download_gib": 2.0,
        }
    }
    decision = choose_max_data_job(
        family_decisions=family_decisions,
        suite_plans=suite_plans,
        completed_suites=("economic-full",),
        free_disk_gib=100.0,
        all_targets_reached=False,
        reserve_gib=25.0,
    )
    assert decision["status"] == "READY"
    assert decision["recommended_suite"] == "copy-vault-full"
    assert decision["recommended_mode"] == "economic"
    assert decision["holdout_used_for_ranking"] is False
