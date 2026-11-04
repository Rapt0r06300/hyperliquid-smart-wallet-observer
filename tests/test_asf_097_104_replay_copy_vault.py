from __future__ import annotations

import pytest

from hl_observer.backtesting.replay_engine import replay_boundary_safety_receipt


def _result() -> dict[str, object]:
    return {
        "status": "PROVEN",
        "paper_read_only": True,
        "real_execution": False,
        "compared": 2,
        "event_ids": ("a", "b"),
    }


@pytest.mark.parametrize("task_id", [f"ASF-{number:03d}" for number in range(97, 105)])
def test_replay_receipt_proves_only_deterministic_paper_replay(task_id: str) -> None:
    del task_id
    receipt = replay_boundary_safety_receipt(_result())
    assert receipt == {
        "status": "PROVEN",
        "verdict": "REPLAY_PAPER_ONLY",
        "paper_read_only": True,
        "real_execution": False,
        "economic_verdict": "UNMEASURABLE",
        "promotion": False,
        "fail_closed": False,
    }


@pytest.mark.parametrize(
    "field, value",
    [
        ("status", "FAILED"),
        ("paper_read_only", False),
        ("real_execution", True),
        ("compared", -1),
        ("compared", True),
        ("event_ids", ["a"]),
        ("event_ids", None),
        ("result", None),
    ],
)
def test_replay_receipt_rejects_invalid_or_unsafe_result(field: str, value: object) -> None:
    result: object = _result()
    if field == "result":
        result = value
    else:
        assert isinstance(result, dict)
        result[field] = value
    receipt = replay_boundary_safety_receipt(result)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True
