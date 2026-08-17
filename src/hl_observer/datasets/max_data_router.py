"""Routing layer for MAX DATA decisions without weakening the canonical policy.

The canonical selector decides *which* suite is useful using disk, provenance,
completed-suite and economic-target constraints.  This layer changes only the
execution mode of active-family FULL/COLD suites so they use the already
implemented economic multi-source adapter instead of the generic historical
stack.  Ranking and holdout rules are untouched.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from hl_observer.datasets import max_data_policy as canonical_policy
from hl_observer.ops.autonomous_research_job_router import FAMILY_ECONOMIC_SUITES

_CANONICAL_CHOOSE = canonical_policy.choose_max_data_job


def route_decision(decision: Mapping[str, Any]) -> dict[str, Any]:
    routed = dict(decision)
    suite = str(routed.get("recommended_suite") or "")
    if routed.get("status") == "READY" and suite in FAMILY_ECONOMIC_SUITES:
        routed["recommended_mode"] = "economic"
        routed["execution_route"] = "ACTIVE_FAMILY_FULL_COLD_ECONOMIC_ADAPTER"
        routed["routing_changed_only_mode"] = True
    else:
        routed.setdefault("execution_route", "CANONICAL")
        routed.setdefault("routing_changed_only_mode", False)
    return routed


def choose_max_data_job(
    *,
    family_decisions: Iterable[Mapping[str, Any]],
    suite_plans: Mapping[str, Mapping[str, Any]],
    completed_suites: Iterable[str] = (),
    free_disk_gib: float,
    all_targets_reached: bool,
    reserve_gib: float = canonical_policy.DEFAULT_RESERVE_GIB,
) -> dict[str, Any]:
    decision = _CANONICAL_CHOOSE(
        family_decisions=family_decisions,
        suite_plans=suite_plans,
        completed_suites=completed_suites,
        free_disk_gib=free_disk_gib,
        all_targets_reached=all_targets_reached,
        reserve_gib=reserve_gib,
    )
    return route_decision(decision)


def main(argv: list[str] | None = None) -> int:
    original = canonical_policy.choose_max_data_job
    canonical_policy.choose_max_data_job = choose_max_data_job
    try:
        return canonical_policy.main(argv)
    finally:
        canonical_policy.choose_max_data_job = original


__all__ = ["choose_max_data_job", "main", "route_decision"]


if __name__ == "__main__":
    raise SystemExit(main())
