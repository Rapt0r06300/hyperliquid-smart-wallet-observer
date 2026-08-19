from __future__ import annotations

import asyncio

import httpx
import pytest

import hl_observer.hyperliquid.rest_info_client as info
from hl_observer.hyperliquid.schemas import OrderStatusKind


def test_payload_builders_and_order_status() -> None:
    assert info.build_all_mids_payload() == {"type": "allMids"}
    assert info.build_meta_payload() == {"type": "meta"}
    assert info.build_active_asset_ctx_payload("btc")["coin"] == "BTC"
    assert info.build_l2_book_payload("eth")["coin"] == "ETH"
    assert info.build_user_fills_payload("u", True)["aggregateByTime"] is True
    with pytest.raises(ValueError):
        info.build_user_fills_by_time_payload("u", 2, 2)
    assert info.build_user_fills_by_time_payload("u", 1, 2)["type"] == "userFillsByTime"
    with pytest.raises(ValueError):
        info.build_funding_history_payload("btc", 2, 2)
    assert info.build_funding_history_payload("btc", 1, 2)["coin"] == "BTC"
    with pytest.raises(ValueError):
        info.build_candle_snapshot_payload("btc", "1m", 2, 2)
    assert info.build_candle_snapshot_payload("btc", "1m", 1, 2)["req"]["coin"] == "BTC"
    info._ensure_read_only_payload({"type": "allMids"})
    with pytest.raises(info.HyperliquidInfoError):
        info._ensure_read_only_payload({"type": "not-allowed"})
    assert info.stable_json_hash({"b": 2, "a": 1}) == info.stable_json_hash({"a": 1, "b": 2})
    known = info.map_order_status({"status": "filled"})
    assert known.status == OrderStatusKind.FILLED and known.is_rejected is False
    assert info.map_order_status({"status": "mystery"}).status == OrderStatusKind.UNKNOWN
    rejected = next(iter(info.REJECTED_ORDER_STATUSES))
    assert info.map_order_status({"status": rejected.value}).is_rejected is True


class _Limiter:
    def __init__(self) -> None:
        self.calls = 0

    async def wait(self) -> None:
        self.calls += 1


class _Response:
    def __init__(self, data=None, *, failure: Exception | None = None) -> None:
        self.data = data
        self.failure = failure

    def raise_for_status(self) -> None:
        if self.failure:
            raise self.failure

    def json(self):
        return self.data


class _Client:
    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.posts = []

    async def post(self, url, json):
        self.posts.append((url, json))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    async def aclose(self) -> None:
        return None


def test_post_info_retry_and_typed_guards(monkeypatch) -> None:
    limiter = _Limiter()
    client = _Client([
        httpx.ConnectError("offline", request=httpx.Request("POST", "https://x/info")),
        _Response({"BTC": "1"}),
    ])
    monkeypatch.setattr(info, "assert_info_endpoint_only", lambda url: None)
    sleeps = []

    async def fake_sleep(value: float) -> None:
        sleeps.append(value)

    monkeypatch.setattr(info.asyncio, "sleep", fake_sleep)
    subject = info.HyperliquidInfoClient(
        "https://x/info",
        client=client,
        rate_limiter=limiter,
        max_retries=1,
        backoff_base_seconds=0.5,
    )
    assert asyncio.run(subject.all_mids()) == {"BTC": "1"}
    assert limiter.calls == 2 and sleeps == [0.5]
    assert client.posts[-1][1]["type"] == "allMids"

    async def wrong(*args, **kwargs):
        return []

    monkeypatch.setattr(subject, "_post_info", wrong)
    with pytest.raises(info.HyperliquidInfoError, match="non-object"):
        asyncio.run(subject.meta())


def test_user_fills_pagination_duplicate_and_timestamp_guards(monkeypatch) -> None:
    subject = info.HyperliquidInfoClient("https://x/info", client=_Client([]))

    async def exercise() -> None:
        duplicate = [{"time": 5}] * info.MAX_USER_FILLS_PAGE_SIZE

        async def duplicate_page(*args, **kwargs):
            return duplicate

        monkeypatch.setattr(subject, "user_fills_by_time", duplicate_page)
        with pytest.raises(info.HyperliquidInfoError, match="Duplicate"):
            async for _ in subject.iter_user_fills_by_time("u", 1, 20, page_window_ms=5):
                pass

        async def no_times(*args, **kwargs):
            return [{}] * info.MAX_USER_FILLS_PAGE_SIZE

        monkeypatch.setattr(subject, "user_fills_by_time", no_times)
        with pytest.raises(info.HyperliquidInfoError, match="without fill timestamps"):
            async for _ in subject.iter_user_fills_by_time("u", 1, 10):
                pass

        with pytest.raises(info.HyperliquidInfoError, match="window did not advance"):
            async for _ in subject.iter_user_fills_by_time("u", 1, 3, page_window_ms=-1):
                pass

    asyncio.run(exercise())
