from __future__ import annotations

import asyncio

import pytest

from hl_observer.collection import weight_budgeter
from hl_observer.hyperliquid.rate_weights import (
    HYPERSMART_EXPLORER_WEIGHT,
    HYPERSMART_INFO_TIME_RANGE_PAGE_LIMIT,
    HYPERSMART_REST_WEIGHT_PER_MIN_PER_IP,
    HYPERSMART_USER_FILLS_BY_TIME_MAX_RECENT,
    HYPERSMART_USER_FILLS_RECENT_LIMIT,
    HYPERSMART_USER_TWAP_SLICE_FILLS_RECENT_LIMIT,
    HYPERSMART_WS_IDLE_TIMEOUT_SECONDS,
    HYPERSMART_WS_MAX_CONNECTIONS,
    HYPERSMART_WS_MAX_INFLIGHT_POST_MESSAGES,
    HYPERSMART_WS_MAX_MESSAGES_PER_MIN,
    HYPERSMART_WS_MAX_NEW_CONNECTIONS_PER_MIN,
    HYPERSMART_WS_MAX_SUBSCRIPTIONS,
    HYPERSMART_WS_MAX_UNIQUE_USERS,
    hyperliquid_info_weight,
)
from hl_observer.hyperliquid.rest_info_client import (
    READ_ONLY_INFO_TYPES,
    HyperliquidInfoClient,
    HyperliquidInfoError,
    build_user_fills_by_time_payload,
    build_user_twap_slice_fills_payload,
)
from hl_observer.realtime import global_ws_budget

WALLET = "0x" + "a" * 40


def test_current_documented_rest_and_response_limits_are_endpoint_specific() -> None:
    assert HYPERSMART_REST_WEIGHT_PER_MIN_PER_IP == 1_200
    assert HYPERSMART_INFO_TIME_RANGE_PAGE_LIMIT == 500
    assert HYPERSMART_USER_FILLS_RECENT_LIMIT == 2_000
    assert HYPERSMART_USER_FILLS_BY_TIME_MAX_RECENT == 10_000
    assert HYPERSMART_USER_TWAP_SLICE_FILLS_RECENT_LIMIT == 2_000
    assert HYPERSMART_EXPLORER_WEIGHT == 40


def test_current_documented_info_weights_include_one_per_twenty_items() -> None:
    assert hyperliquid_info_weight("allMids") == 2
    assert hyperliquid_info_weight("clearinghouseState") == 2
    assert hyperliquid_info_weight("openOrders") == 20
    assert hyperliquid_info_weight("userRole") == 60
    assert hyperliquid_info_weight("userFillsByTime", returned_items=0) == 20
    assert hyperliquid_info_weight("userFillsByTime", returned_items=1) == 21
    assert hyperliquid_info_weight("userFillsByTime", returned_items=41) == 23
    assert hyperliquid_info_weight("candleSnapshot", returned_items=61) == 22


def test_current_documented_websocket_limits_have_one_source_of_truth() -> None:
    assert HYPERSMART_WS_MAX_CONNECTIONS == 10
    assert HYPERSMART_WS_MAX_NEW_CONNECTIONS_PER_MIN == 30
    assert HYPERSMART_WS_MAX_SUBSCRIPTIONS == 1_000
    assert HYPERSMART_WS_MAX_UNIQUE_USERS == 10
    assert HYPERSMART_WS_MAX_MESSAGES_PER_MIN == 2_000
    assert HYPERSMART_WS_MAX_INFLIGHT_POST_MESSAGES == 100
    assert HYPERSMART_WS_IDLE_TIMEOUT_SECONDS == 60
    assert global_ws_budget.WS_MAX_CONNECTIONS == HYPERSMART_WS_MAX_CONNECTIONS
    assert (
        global_ws_budget.WS_MAX_MESSAGES_PER_MINUTE
        == HYPERSMART_WS_MAX_MESSAGES_PER_MIN
    )
    assert weight_budgeter.WS_MAX_UNIQUE_USERS == HYPERSMART_WS_MAX_UNIQUE_USERS


def test_user_fills_by_time_payload_uses_inclusive_documented_range() -> None:
    assert build_user_fills_by_time_payload(
        WALLET,
        1_000,
        2_000,
        aggregate_by_time=True,
    ) == {
        "type": "userFillsByTime",
        "user": WALLET,
        "startTime": 1_000,
        "endTime": 2_000,
        "aggregateByTime": True,
    }


def test_twap_slice_fills_is_an_explicit_read_only_info_contract() -> None:
    assert "userTwapSliceFills" in READ_ONLY_INFO_TYPES
    assert build_user_twap_slice_fills_payload(WALLET) == {
        "type": "userTwapSliceFills",
        "user": WALLET,
    }


def test_twap_slice_fills_client_accepts_documented_shape() -> None:
    class _Response:
        status_code = 200

        def json(self):
            return [
                {
                    "fill": {
                        "coin": "HYPE",
                        "tid": 7,
                        "hash": "0x" + "0" * 64,
                    },
                    "twapId": 3156,
                }
            ]

        def raise_for_status(self) -> None:
            return None

    class _Http:
        def __init__(self) -> None:
            self.payload = None

        async def post(self, _url, *, json):
            self.payload = json
            return _Response()

        async def aclose(self) -> None:
            return None

    http = _Http()
    client = HyperliquidInfoClient(client=http)
    result = asyncio.run(client.user_twap_slice_fills(WALLET))

    assert http.payload == {"type": "userTwapSliceFills", "user": WALLET}
    assert result[0]["twapId"] == 3156
    assert result[0]["fill"]["tid"] == 7


def test_twap_slice_fills_client_rejects_invalid_response_shape() -> None:
    class _Response:
        status_code = 200

        def json(self):
            return {"not": "a list"}

        def raise_for_status(self) -> None:
            return None

    class _Http:
        async def post(self, _url, *, json):
            return _Response()

        async def aclose(self) -> None:
            return None

    client = HyperliquidInfoClient(client=_Http())
    with pytest.raises(HyperliquidInfoError, match="non-list"):
        asyncio.run(client.user_twap_slice_fills(WALLET))
