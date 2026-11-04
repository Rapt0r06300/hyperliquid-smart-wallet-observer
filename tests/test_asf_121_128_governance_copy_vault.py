from __future__ import annotations

import pytest

from tools.check_repo_governance import governance_safety_receipt, local_failures


@pytest.mark.parametrize("task_id", [f"ASF-{number:03d}" for number in range(121, 129)])
def test_governance_receipt_accepts_green_local_gate(task_id: str) -> None:
    del task_id
    receipt = governance_safety_receipt(local_failures())
    assert receipt == {
        "status": "PROVEN",
        "verdict": "REPOSITORY_GOVERNANCE_GREEN",
        "paper_read_only": True,
        "real_execution": False,
        "mutation": False,
        "failure_count": 0,
        "fail_closed": False,
    }


@pytest.mark.parametrize("failures", [None, {}, ["missing"], ["unsafe", "drift"], "failure"])
def test_governance_receipt_rejects_non_green_results(failures: object) -> None:
    receipt = governance_safety_receipt(failures)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True
