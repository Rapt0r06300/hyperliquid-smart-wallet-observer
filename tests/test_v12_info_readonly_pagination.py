from __future__ import annotations

import asyncio

from hl_observer.hyperliquid.info_readonly import fetch_user_fills_by_time_bounded
from hl_observer.hyperliquid.rate_weights import (
    HYPERSMART_EXPLORER_WEIGHT,
    HYPERSMART_INFO_TIME_RANGE_PAGE_LIMIT,
    HYPERSMART_MAX_FILLS_PER_RUN,
    HYPERSMART_MAX_PAGES_PER_WALLET,
    HYPERSMART_REST_WEIGHT_PER_MIN_PER_IP,
    HYPERSMART_USER_FILLS_RECENT_LIMIT,
    HYPERSMART_WS_MAX_CONNECTIONS,
    HYPERSMART_WS_MAX_NEW_CONNECTIONS_PER_MIN,
    HYPERSMART_WS_MAX_SUBSCRIPTIONS,
    HYPERSMART_WS_MAX_UNIQUE_USERS,
)


class FakeFillsClient:
    def __init__(self, pages: list[list[dict]]) -> None:
        self.pages = list(pages)
        self.calls: list[tuple[str, int, int]] = []

    async def user_fills_by_time(self, user: str, start_time: int, end_time: int) -> list[dict]:
        self.calls.append((user, start_time, end_time))
        if not self.pages:
            return []
        return self.pages.pop(0)


def test_v12_rate_limit_constants_are_conservative():
    assert HYPERSMART_INFO_TIME_RANGE_PAGE_LIMIT == 500
    assert HYPERSMART_USER_FILLS_RECENT_LIMIT == 2000
    assert HYPERSMART_MAX_PAGES_PER_WALLET >= 1
    assert HYPERSMART_MAX_FILLS_PER_RUN >= HYPERSMART_INFO_TIME_RANGE_PAGE_LIMIT
    assert HYPERSMART_REST_WEIGHT_PER_MIN_PER_IP == 1200
    assert HYPERSMART_WS_MAX_CONNECTIONS == 10
    assert HYPERSMART_WS_MAX_NEW_CONNECTIONS_PER_MIN == 30
    assert HYPERSMART_WS_MAX_SUBSCRIPTIONS == 1000
    assert HYPERSMART_WS_MAX_UNIQUE_USERS == 10
    assert HYPERSMART_EXPLORER_WEIGHT == 40


def test_v12_user_fills_pagination_advances_by_last_timestamp_plus_one():
    client = FakeFillsClient(
        [
            [{"time": 1000, "hash": "a"}, {"time": 1005, "hash": "b"}],
            [{"time": 1010, "hash": "c"}],
            [],
        ]
    )

    result = asyncio.run(
        fetch_user_fills_by_time_bounded(
            client,
            user="0xabc",
            start_time=1000,
            end_time=2000,
            max_pages=5,
            max_fills=10,
        )
    )

    assert [call[1] for call in client.calls] == [1000, 1006, 1011]
    assert [fill["hash"] for fill in result.fills] == ["a", "b", "c"]
    assert result.stopped_reason == "empty_response"


def test_v12_user_fills_pagination_stops_on_max_pages():
    client = FakeFillsClient([[{"time": 1}], [{"time": 2}], [{"time": 3}]])

    result = asyncio.run(
        fetch_user_fills_by_time_bounded(client, user="0xabc", start_time=1, end_time=10, max_pages=2)
    )

    assert result.pages_fetched == 2
    assert result.stopped_reason == "max_pages_reached"


def test_v12_user_fills_pagination_stops_on_timestamp_not_progressing():
    client = FakeFillsClient([[{"time": 100, "hash": "a"}], [{"time": 100, "hash": "b"}]])

    result = asyncio.run(
        fetch_user_fills_by_time_bounded(client, user="0xabc", start_time=100, end_time=200, max_pages=3)
    )

    assert result.stopped_reason == "timestamp_not_progressing"


def test_v12_user_fills_pagination_stops_on_max_fills_and_truncates_page():
    oversized = [{"time": 1000 + index, "hash": str(index)} for index in range(600)]
    client = FakeFillsClient([oversized])

    result = asyncio.run(
        fetch_user_fills_by_time_bounded(
            client,
            user="0xabc",
            start_time=1000,
            end_time=5000,
            max_pages=2,
            max_fills=100,
            page_limit=500,
        )
    )

    assert len(result.fills) == 100
    assert result.stopped_reason == "max_fills_reached"
    assert "PAGE_LIMIT_TRUNCATED_TO_500" in result.warnings
