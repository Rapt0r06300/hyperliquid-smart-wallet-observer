from __future__ import annotations

import pytest

from hl_observer.ops.daily_economic_certification import daily_certification_safety_receipt


def _result() -> dict[str, object]:
    return {
        "status": "NO_GO",
        "all_families_certified": False,
        "daily_rate_basis": "VERIFIED_STRICT_POST_FREEZE_FORWARD_WALL_CLOCK",
        "families": {},
    }


@pytest.mark.parametrize("task_id", [f"ASF-{number:03d}" for number in range(105, 113)])
def test_daily_certification_receipt_is_fail_closed_and_paper_only(task_id: str) -> None:
    del task_id
    receipt = daily_certification_safety_receipt(_result())
    assert receipt == {
        "status": "PROVEN",
        "verdict": "DAILY_CERTIFICATION_SAFE",
        "paper_read_only": True,
        "real_execution": False,
        "economic_verdict": "UNMEASURABLE",
        "automatic_activation": False,
        "fail_closed": False,
    }


@pytest.mark.parametrize(
    "field, value",
    [
        ("status", "CERTIFIED"),
        ("all_families_certified", "yes"),
        ("daily_rate_basis", "ARBITRARY"),
        ("families", None),
        ("paper_read_only", False),
        ("real_execution", True),
        ("automatic_activation", True),
        ("result", None),
    ],
)
def test_daily_certification_receipt_rejects_unsafe_or_malformed_result(
    field: str, value: object
) -> None:
    result: object = _result()
    if field == "result":
        result = value
    else:
        assert isinstance(result, dict)
        result[field] = value
    receipt = daily_certification_safety_receipt(result)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True
