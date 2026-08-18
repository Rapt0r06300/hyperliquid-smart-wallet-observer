"""Pure routing layer for MAX DATA decisions.

No global monkeypatching: the canonical selector is called explicitly and the
family execution mode is transformed in the returned value only.
"""
from __future__ import annotations

import argparse
import shutil
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from hl_observer.datasets import max_data_policy as canonical_policy
from hl_observer.ops.family_economic_job import FAMILY_ECONOMIC_SUITES


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
    return route_decision(
        canonical_policy.choose_max_data_job(
            family_decisions=family_decisions,
            suite_plans=suite_plans,
            completed_suites=completed_suites,
            free_disk_gib=free_disk_gib,
            all_targets_reached=all_targets_reached,
            reserve_gib=reserve_gib,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Choisit la prochaine suite MAX DATA sans mutation globale."
    )
    parser.add_argument("--brain-json", required=True)
    parser.add_argument("--lab-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--completed-suite", action="append", default=[])
    parser.add_argument("--project-sha", default=None)
    parser.add_argument("--reserve-gib", type=float, default=canonical_policy.DEFAULT_RESERVE_GIB)
    args = parser.parse_args(argv)

    brain = canonical_policy._load_json(Path(args.brain_json))
    raw = brain.get("family_decisions")
    if not isinstance(raw, list):
        raise ValueError("family_decisions absent du rapport du cerveau.")
    decisions = [row for row in raw if isinstance(row, Mapping)]
    lab_root = Path(args.lab_root).resolve()
    plans = canonical_policy.load_suite_plans(lab_root)
    if not plans:
        raise ValueError("BIBLIOTHEQUE_180GO.json absente ou sans plans.")
    persisted = canonical_policy.completed_suites_from_registry(lab_root, project_sha=args.project_sha)
    completed = sorted(set(args.completed_suite) | set(persisted))
    free_gib = shutil.disk_usage(lab_root).free / (1024**3)
    decision = choose_max_data_job(
        family_decisions=decisions,
        suite_plans=plans,
        completed_suites=completed,
        free_disk_gib=free_gib,
        all_targets_reached=canonical_policy.targets_reached_from_brain(decisions),
        reserve_gib=args.reserve_gib,
    )
    decision["completed_registry_path"] = str(canonical_policy.completed_registry_path(lab_root))
    decision["project_sha_scope"] = str(args.project_sha or "ALL_RECORDED_SHA")
    json_path, md_path = canonical_policy.write_decision(args.output_dir, decision)
    print(
        "ALINA_MAX_DATA "
        f"status={decision['status']} suite={decision.get('recommended_suite')} "
        f"mode={decision.get('recommended_mode')} json={json_path} md={md_path}",
        flush=True,
    )
    return 0 if decision["status"] in {"READY", "STOP_PROOF_REACHED"} else 4


__all__ = ["choose_max_data_job", "main", "route_decision"]


if __name__ == "__main__":
    raise SystemExit(main())
