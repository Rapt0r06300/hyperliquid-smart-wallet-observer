from __future__ import annotations

import pytest

from hl_observer.ops.pnl_improvement_lab import pnl_research_governance_receipt


def _result() -> dict[str, object]:
    return {
        "strategy_family": "Copy-Vault",
        "promotion": False,
        "financial_target": None,
        "champions_append_only": True,
        "challenger_count": 4,
        "oos_reused_for_tuning": False,
        "cpu_first": True,
        "safe_replay": True,
        "launcher_audit": True,
        "receipt_complete": True,
        "snapshot": {
            "status": "FREEZE_EXPLORATORY",
            "dataset_sha256": "a" * 64,
            "window": "TRAIN/OOS/FORWARD",
            "seed": 17,
            "trial_count": 4,
            "costs": {"fee_bps": 9.0, "slippage_bps": 1.0},
        },
    }


@pytest.mark.parametrize("task_id", [f"ASF-{number:03d}" for number in range(137, 151)])
def test_pnl_research_receipt_requires_immutable_governance(task_id: str) -> None:
    del task_id
    receipt = pnl_research_governance_receipt(_result())
    assert receipt == {
        "status": "PROVEN",
        "verdict": "PNL_RESEARCH_GOVERNED",
        "paper_read_only": True,
        "real_execution": False,
        "economic_verdict": "UNMEASURABLE",
        "promotion": False,
        "fail_closed": False,
    }


@pytest.mark.parametrize(
    "path, value",
    [
        (("strategy_family",), "Lead-Lag"),
        (("promotion",), True),
        (("financial_target",), 5.0),
        (("challenger_count",), 3),
        (("oos_reused_for_tuning",), True),
        (("snapshot", "dataset_sha256"), "not-a-hash"),
        (("snapshot", "trial_count"), -1),
        (("snapshot", "status"), "PROMOTED"),
    ],
)
def test_pnl_research_receipt_rejects_governance_bypass(path: tuple[str, ...], value: object) -> None:
    result: object = _result()
    assert isinstance(result, dict)
    target: dict[str, object] = result
    for key in path[:-1]:
        nested = target[key]
        assert isinstance(nested, dict)
        target = nested
    target[path[-1]] = value
    receipt = pnl_research_governance_receipt(result)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True
