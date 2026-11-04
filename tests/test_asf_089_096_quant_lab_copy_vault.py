from __future__ import annotations

import pytest

from tools.alina_quant_lab_console import quant_lab_safety_receipt


def _result() -> dict[str, object]:
    return {
        "paper_read_only": True,
        "network_or_collection_started": False,
        "freeze_verdict": "VALID_PHYSICAL_FREEZE",
        "economic_result": {
            "comparison_performed": False,
            "best_strategy_proven": False,
            "measured_profit_usd": None,
        },
    }


@pytest.mark.parametrize("task_id", [f"ASF-{number:03d}" for number in range(89, 97)])
def test_quant_lab_receipt_proves_local_paper_boundary(task_id: str) -> None:
    del task_id
    receipt = quant_lab_safety_receipt(_result())
    assert receipt == {
        "status": "PROVEN",
        "verdict": "QUANT_LAB_PAPER_ONLY",
        "paper_read_only": True,
        "network_or_collection_started": False,
        "economic_verdict": "UNMEASURABLE",
        "automatic_activation": False,
        "fail_closed": False,
    }


@pytest.mark.parametrize(
    "field, value",
    [
        ("paper_read_only", False),
        ("network_or_collection_started", True),
        ("freeze_verdict", None),
        ("economic_result", None),
        ("economic_result", {"comparison_performed": True, "best_strategy_proven": False, "measured_profit_usd": None}),
        ("economic_result", {"comparison_performed": False, "best_strategy_proven": True, "measured_profit_usd": None}),
        ("economic_result", {"comparison_performed": False, "best_strategy_proven": False, "measured_profit_usd": 1.0}),
        ("result", None),
    ],
)
def test_quant_lab_receipt_rejects_unsafe_or_economic_claim(
    field: str, value: object
) -> None:
    result: object = _result()
    if field == "result":
        result = value
    else:
        assert isinstance(result, dict)
        result[field] = value
    receipt = quant_lab_safety_receipt(result)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True
