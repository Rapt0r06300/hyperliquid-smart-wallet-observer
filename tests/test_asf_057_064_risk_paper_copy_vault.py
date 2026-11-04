from __future__ import annotations

import pytest

from hl_observer.ops.paper_pipeline_e2e import paper_pipeline_safety_receipt
from hl_observer.risk.advanced_risk_manager import risk_engine_safety_receipt


@pytest.mark.parametrize("task_id", [f"ASF-{number:03d}" for number in range(57, 61)])
def test_risk_receipt_accepts_only_paper_report(task_id: str) -> None:
    del task_id
    receipt = risk_engine_safety_receipt(
        {"simulation_only": True, "real_orders_created": 0}
    )
    assert receipt == {
        "status": "PROVEN",
        "verdict": "RISK_ENGINE_PAPER_ONLY",
        "paper_read_only": True,
        "real_execution": False,
        "risk_mutation": False,
        "fail_closed": False,
    }


@pytest.mark.parametrize(
    "result",
    [
        {"simulation_only": False, "real_orders_created": 0},
        {"simulation_only": True, "real_orders_created": 1},
        None,
        {"simulation_only": True},
    ],
)
def test_risk_receipt_rejects_missing_or_unsafe_report(result: object) -> None:
    receipt = risk_engine_safety_receipt(result)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True


@pytest.mark.parametrize("task_id", [f"ASF-{number:03d}" for number in range(61, 65)])
def test_pipeline_receipt_accepts_technical_paper_result(task_id: str) -> None:
    del task_id
    receipt = paper_pipeline_safety_receipt(
        {
            "paper_only": True,
            "real_execution": False,
            "economic_verdict": "UNMEASURABLE",
            "closure_allowed": False,
            "stages": ["SAFE", "PAPER"],
        }
    )
    assert receipt == {
        "status": "PROVEN",
        "verdict": "PAPER_PIPELINE_SAFE",
        "paper_only": True,
        "real_execution": False,
        "economic_promotion": False,
        "mutation": False,
        "fail_closed": False,
    }


@pytest.mark.parametrize(
    "result",
    [
        {"paper_only": True, "real_execution": True, "economic_verdict": "UNMEASURABLE", "closure_allowed": False, "stages": ["SAFE"]},
        {"paper_only": True, "real_execution": False, "economic_verdict": "UNMEASURABLE", "closure_allowed": True, "stages": ["SAFE"]},
        {"paper_only": True, "real_execution": False, "economic_verdict": "UNMEASURABLE", "closure_allowed": False, "stages": []},
        None,
    ],
)
def test_pipeline_receipt_rejects_unsafe_or_incomplete_result(result: object) -> None:
    receipt = paper_pipeline_safety_receipt(result)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True
