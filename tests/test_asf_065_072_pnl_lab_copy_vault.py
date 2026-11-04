from __future__ import annotations

import pytest

from hl_observer.ops.pnl_improvement_lab import pnl_lab_safety_receipt


def _report() -> dict[str, object]:
    return {
        "local_historical_data_only": True,
        "network_used": False,
        "real_execution": False,
        "automatic_activation": False,
        "truth": {},
        "temporal_validation": {"status": "UNMEASURABLE"},
        "experiment_backlog": [],
    }


@pytest.mark.parametrize("task_id", [f"ASF-{number:03d}" for number in range(65, 73)])
def test_pnl_lab_receipt_proves_only_safe_paper_boundary(task_id: str) -> None:
    del task_id
    receipt = pnl_lab_safety_receipt(_report())
    assert receipt == {
        "status": "PROVEN",
        "verdict": "PNL_LAB_PAPER_ONLY",
        "economic_verdict": "UNMEASURABLE",
        "paper_read_only": True,
        "real_execution": False,
        "automatic_activation": False,
        "promotion": False,
        "fail_closed": False,
    }


@pytest.mark.parametrize(
    "field, value",
    [
        ("local_historical_data_only", False),
        ("network_used", True),
        ("real_execution", True),
        ("automatic_activation", True),
        ("truth", None),
        ("temporal_validation", None),
        ("experiment_backlog", None),
        ("report", None),
    ],
)
def test_pnl_lab_receipt_rejects_unsafe_or_incomplete_report(
    field: str, value: object
) -> None:
    report: object = _report()
    if field == "report":
        report = value
    else:
        assert isinstance(report, dict)
        report[field] = value
    receipt = pnl_lab_safety_receipt(report)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True
