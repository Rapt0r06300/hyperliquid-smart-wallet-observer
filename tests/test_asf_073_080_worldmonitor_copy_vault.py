from __future__ import annotations

import pytest

from hl_observer.event_intelligence.worldmonitor import worldmonitor_safety_receipt


def _result() -> dict[str, object]:
    return {
        "read_only": True,
        "real_execution": False,
        "mutation": False,
        "variants": [
            {"surface": "/api/intelligence/v1/list-cross-source-signals", "read_only": True},
            {"surface": "/api/news/v1/list-feed-digest", "read_only": True},
            {"surface": "/api/prediction/v1/list-prediction-markets", "read_only": True},
            {"surface": "derived:news_digest", "read_only": True},
            {"surface": "derived:news_digest", "read_only": True},
            {"surface": "derived:prediction_markets", "read_only": True},
        ],
    }


@pytest.mark.parametrize("task_id", [f"ASF-{number:03d}" for number in range(73, 81)])
def test_worldmonitor_receipt_proves_bounded_read_only_surface(task_id: str) -> None:
    del task_id
    receipt = worldmonitor_safety_receipt(_result())
    assert receipt == {
        "status": "PROVEN",
        "verdict": "WORLDMONITOR_READ_ONLY",
        "read_only": True,
        "real_execution": False,
        "mutation": False,
        "economic_verdict": "UNMEASURABLE",
        "fail_closed": False,
    }


@pytest.mark.parametrize(
    "field, value",
    [
        ("read_only", False),
        ("real_execution", True),
        ("mutation", True),
        ("variants", []),
        ("variants", [{"surface": "/bad", "read_only": True}] * 6),
        ("variants", [{"surface": "/ok", "read_only": False}] * 6),
        ("variants", None),
        ("result", None),
    ],
)
def test_worldmonitor_receipt_rejects_unsafe_surface(field: str, value: object) -> None:
    result: object = _result()
    if field == "result":
        result = value
    else:
        assert isinstance(result, dict)
        result[field] = value
    receipt = worldmonitor_safety_receipt(result)
    assert receipt["status"] == "REJECTED"
    assert receipt["fail_closed"] is True
