from __future__ import annotations

import pytest

from hl_observer.ops.paper_pipeline_e2e import (
    e2e_technical_closure_receipt,
)


def _result() -> dict[str, object]:
    return {
        "paper_only": True,
        "real_execution": False,
        "economic_verdict": "UNMEASURABLE",
        "closure_allowed": False,
        "stages": ["SAFE", "WALLET", "SIGNAL", "RISK", "PAPER", "LEDGER", "OOS"],
        "errors": ["FORWARD_EVIDENCE_MISSING"],
    }


@pytest.mark.parametrize("task_id", [f"ASF-{number:03d}" for number in range(129, 137)])
def test_e2e_receipt_requires_complete_technical_chain(task_id: str) -> None:
    del task_id
    receipt = e2e_technical_closure_receipt(_result())
    assert receipt == {
        "status": "PROVEN",
        "verdict": "E2E_TECHNICAL_SAFE",
        "paper_only": True,
        "real_execution": False,
        "economic_verdict": "UNMEASURABLE",
        "closure_allowed": False,
        "promotion": False,
        "fail_closed": False,
    }


@pytest.mark.parametrize(
    "field, value",
    [
        ("paper_only", False),
        ("real_execution", True),
        ("economic_verdict", "PROVEN"),
        ("closure_allowed", True),
        ("stages", ["SAFE"]),
        ("errors", []),
        ("errors", [None]),
        ("result", None),
    ],
)
def test_e2e_receipt_rejects_incomplete_or_promoted_result(field: str, value: object) -> None:
    result: object = _result()
    if field == "result":
        result = value
    else:
        assert isinstance(result, dict)
        result[field] = value
    receipt = e2e_technical_closure_receipt(result)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True
