from __future__ import annotations

from hl_observer.backtesting.copy_vault_task_closure_plans import (
    TASK_IDS,
    build_task_closure_plans,
    evaluate_tasklist,
)


HEAD = "2c550287593c9578c36f534705f10511d9082d6c"


def test_plan_covers_exactly_the_ten_remaining_copy_vault_tasks() -> None:
    plans = build_task_closure_plans()
    assert tuple(plans) == TASK_IDS
    assert len(plans) == 10
    assert all(criteria for criteria in plans.values())


def test_empty_receipts_never_promote_any_task() -> None:
    report = evaluate_tasklist({}, expected_head_sha=HEAD)
    assert report["global"] == {
        "done": 0,
        "testing": 10,
        "blocked": 2,
        "total": 10,
        "closure_allowed": False,
    }
    assert all(row["recommended_agiflow_state"] == "Testing" for row in report["tasks"])


def test_missing_receipts_are_reported_per_task() -> None:
    report = evaluate_tasklist({}, expected_head_sha=HEAD)
    by_id = {row["task_id"]: row for row in report["tasks"]}
    assert any("EVIDENCE_KIND_MISSING" in item for item in by_id["H-T95"]["missing_evidence"])
    assert any("EVIDENCE_KIND_MISSING" in item for item in by_id["H-T170"]["missing_evidence"])
    assert by_id["H-T170"]["external_block"] is True
