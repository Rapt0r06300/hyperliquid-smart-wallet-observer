from __future__ import annotations

import pytest

from hl_observer.event_intelligence.idea_coverage import (
    coverage_summary,
    idea_coverage_safety_receipt,
)


@pytest.mark.parametrize("task_id", [f"ASF-{number:03d}" for number in range(81, 89)])
def test_idea_coverage_receipt_accepts_complete_registry(task_id: str) -> None:
    del task_id
    receipt = idea_coverage_safety_receipt(coverage_summary())
    assert receipt == {
        "status": "PROVEN",
        "verdict": "IDEA_COVERAGE_COMPLETE",
        "paper_read_only": True,
        "real_execution": False,
        "economic_verdict": "UNMEASURABLE",
        "promotion": False,
        "fail_closed": False,
    }


@pytest.mark.parametrize(
    "summary",
    [
        None,
        {},
        {"count": 119, "coverage_valid": True},
        {"count": 120, "min_id": 1, "max_id": 120, "unique_ids": 120, "complete_1_to_120": True, "coverage_valid": False, "statuses": {"IMPLEMENTED": 120}},
        {"count": 120, "min_id": 1, "max_id": 120, "unique_ids": 120, "complete_1_to_120": True, "coverage_valid": True, "statuses": {"IMPLEMENTED": 119, "TESTING": 1}},
        {"count": 120, "min_id": 1, "max_id": 120, "unique_ids": 119, "complete_1_to_120": True, "coverage_valid": True, "statuses": {"IMPLEMENTED": 120}},
        {"count": 120, "min_id": 1, "max_id": 120, "unique_ids": 120, "complete_1_to_120": False, "coverage_valid": True, "statuses": {"IMPLEMENTED": 120}},
        {"count": 120, "min_id": 1, "max_id": 120, "unique_ids": 120, "complete_1_to_120": True, "coverage_valid": True, "statuses": {"IMPLEMENTED": 120}, "real_execution": True},
    ],
)
def test_idea_coverage_receipt_rejects_incomplete_registry(summary: object) -> None:
    receipt = idea_coverage_safety_receipt(summary)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True
