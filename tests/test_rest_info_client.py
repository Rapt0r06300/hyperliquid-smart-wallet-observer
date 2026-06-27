import asyncio

import httpx

from hl_observer.hyperliquid.rest_info_client import (
    HyperliquidInfoClient,
    build_user_fills_by_time_payload,
    map_order_status,
)
from hl_observer.hyperliquid.schemas import OrderStatusKind


def test_user_fills_pagination_contract():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json=[{"time": 10}, {"time": 20}])

    async def run_client():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            client = HyperliquidInfoClient("https://api.hyperliquid.xyz/info", client=http_client)
            return await client.user_fills_by_time("0xabc", 1, 100)

    page = asyncio.run(run_client())

    assert len(page) == 2
    assert len(calls) == 1
    assert build_user_fills_by_time_payload("0xabc", 1, 2) == {
        "type": "userFillsByTime",
        "user": "0xabc",
        "startTime": 1,
        "endTime": 2,
    }


def test_order_status_rejections_are_mapped():
    for raw_status in [
        "rejected",
        "marginCanceled",
        "reduceOnlyCanceled",
        "tickRejected",
        "minTradeNtlRejected",
    ]:
        status = map_order_status({"status": raw_status})
        assert status.is_rejected

    assert map_order_status({"status": "filled"}).status == OrderStatusKind.FILLED
