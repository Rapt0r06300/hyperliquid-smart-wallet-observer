from __future__ import annotations

import asyncio

import pytest

from hl_observer.collection.copy_vault_checkpoint_tail import coverage_receipt
from hl_observer.collection.hyperliquid_funding_history import (
    fetch_hyperliquid_funding_settlements,
)
from hl_observer.collection.vault_fills_backfill import (
    pagination_boundary_receipt,
    parser_fills_with_audit,
    split_inclusive_window,
)
from hl_observer.hyperliquid.rest_info_client import (
    build_user_fills_by_time_payload,
)
from hl_observer.hyperliquid.ws_client import MarketWebSocketClient, MarketWebSocketConfig


class _FundingResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FundingClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def post(self, url, *, json):
        self.calls.append((url, json))
        return _FundingResponse(self.payload)


def test_bug001_boundary_page_is_deduplicated_without_dropping_rows():
    result = pagination_boundary_receipt(
        [[{"time": 1, "tid": "a", "coin": "BTC"}],
         [{"time": 1, "tid": "a", "coin": "BTC"}, {"time": 1, "tid": "b", "coin": "BTC"}]]
    )
    assert result["status"] == "PROVEN"
    assert result["retained_count"] == 2


def test_bug002_same_timestamp_keeps_distinct_native_ids():
    result = pagination_boundary_receipt(
        [[{"time": 1000, "tid": "a", "coin": "BTC"}, {"time": 1000, "tid": "b", "coin": "BTC"}]]
    )
    assert [row["tid"] for row in result["fills"]] == ["a", "b"]


def test_bug003_page_bounds_are_explicit_and_not_silently_unbounded():
    first, second = split_inclusive_window(0, 10)
    assert first[1] + 1 == second[0]
    assert split_inclusive_window(10, 10) is None


def test_bug004_inclusive_cursor_split_has_no_overlap():
    left, right = split_inclusive_window(100, 201)
    assert set(range(left[0], left[1] + 1)).isdisjoint(set(range(right[0], right[1] + 1)))


def test_bug005_aggregate_by_time_is_stable_between_cycles():
    expected = {
        "type": "userFillsByTime",
        "user": "0x" + "a" * 40,
        "startTime": 1,
        "endTime": 2,
        "aggregateByTime": True,
    }
    assert build_user_fills_by_time_payload("0x" + "a" * 40, 1, 2, True) == expected
    assert build_user_fills_by_time_payload("0x" + "a" * 40, 1, 2, True) == expected


def test_bug006_malformed_boundary_identity_fails_closed():
    result = pagination_boundary_receipt([[{"time": 1, "coin": "BTC"}]])
    assert result["status"] == "UNMEASURABLE"


def test_bug007_malformed_fill_is_quarantined_not_zero_filled():
    fills, audit = parser_fills_with_audit([{"time": 1, "coin": "BTC"}], vault="0x" + "a" * 40)
    assert fills == []
    assert audit["rejected_by_reason"]


def test_bug008_ws_user_stream_is_disabled_by_default():
    client = MarketWebSocketClient(MarketWebSocketConfig())
    client.assert_safe()
    with pytest.raises(RuntimeError):
        MarketWebSocketClient(MarketWebSocketConfig(subscribe_user_streams=True)).assert_safe()


def test_bug009_checkpoint_coverage_does_not_promote_missing_lines():
    result = coverage_receipt(
        {"complete_lines": 9, "checkpoints_captured": 9, "invalid_rejected": 1},
        expected_lines=10,
    )
    assert result["status"] == "UNMEASURABLE"


def test_bug010_funding_response_is_bounded_deduplicated_and_read_only():
    client = _FundingClient(
        [
            {"time": 1, "coin": "BTC", "fundingRate": "0.001"},
            {"time": 1, "coin": "BTC", "fundingRate": "0.002"},
            {"time": 2, "coin": "BTC", "fundingRate": "bad"},
        ]
    )
    rows = asyncio.run(
        fetch_hyperliquid_funding_settlements(
            ["BTC"], start_ms=1, end_ms=2, http_client=client
        )
    )
    assert len(rows) == 1
    coverage = rows[0].provenance["coverage_receipt"]
    assert coverage["duplicate_timestamp_rows"] == 1
    assert coverage["rejected_rows"] == 1
    assert coverage["data_gate_ready"] is False
