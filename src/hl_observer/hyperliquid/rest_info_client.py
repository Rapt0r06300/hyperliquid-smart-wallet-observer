from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx

from hl_observer.hyperliquid.rate_limits import AsyncRateLimiter
from hl_observer.hyperliquid.schemas import (
    OrderStatus,
    OrderStatusKind,
    REJECTED_ORDER_STATUSES,
)

MAX_USER_FILLS_PAGE_SIZE = 2000
READ_ONLY_INFO_TYPES = {
    "allMids",
    "l2Book",
    "openOrders",
    "frontendOpenOrders",
    "userFills",
    "userFillsByTime",
    "orderStatus",
    "candleSnapshot",
}


class HyperliquidInfoError(RuntimeError):
    """Raised when a read-only Hyperliquid info call fails."""


def _ensure_read_only_payload(payload: dict[str, Any]) -> None:
    request_type = payload.get("type")
    if request_type not in READ_ONLY_INFO_TYPES:
        raise HyperliquidInfoError(f"Unsupported read-only info type: {request_type!r}")


def build_user_fills_by_time_payload(user: str, start_time: int, end_time: int) -> dict[str, Any]:
    if start_time >= end_time:
        raise ValueError("start_time must be strictly lower than end_time")
    return {
        "type": "userFillsByTime",
        "user": user,
        "startTime": int(start_time),
        "endTime": int(end_time),
    }


def map_order_status(payload: dict[str, Any]) -> OrderStatus:
    raw_status = payload.get("status")
    status = OrderStatusKind.UNKNOWN
    if isinstance(raw_status, str):
        try:
            status = OrderStatusKind(raw_status)
        except ValueError:
            status = OrderStatusKind.UNKNOWN
    return OrderStatus(
        status=status,
        is_rejected=status in REJECTED_ORDER_STATUSES,
        raw=payload,
    )


class HyperliquidInfoClient:
    """Small, read-only client for Hyperliquid's /info API."""

    def __init__(
        self,
        base_url: str = "https://api.hyperliquid.xyz/info",
        *,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        backoff_base_seconds: float = 0.25,
        client: httpx.AsyncClient | None = None,
        rate_limiter: AsyncRateLimiter | None = None,
    ) -> None:
        if not base_url.endswith("/info"):
            raise HyperliquidInfoError("HyperliquidInfoClient must target the /info endpoint only")
        self.base_url = base_url
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        self._client = client
        self._owns_client = client is None
        self._rate_limiter = rate_limiter or AsyncRateLimiter()

    async def __aenter__(self) -> HyperliquidInfoClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
            self._owns_client = True
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()

    async def _post_info(self, payload: dict[str, Any]) -> Any:
        _ensure_read_only_payload(payload)
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
            self._owns_client = True

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            await self._rate_limiter.wait()
            try:
                response = await self._client.post(self.base_url, json=payload)
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep(self.backoff_base_seconds * (2**attempt))
        raise HyperliquidInfoError(f"Hyperliquid /info call failed: {last_error}") from last_error

    async def all_mids(self) -> dict[str, str]:
        data = await self._post_info({"type": "allMids"})
        if not isinstance(data, dict):
            raise HyperliquidInfoError("allMids returned a non-object payload")
        return data

    async def l2_book(self, coin: str) -> dict[str, Any]:
        data = await self._post_info({"type": "l2Book", "coin": coin})
        if not isinstance(data, dict):
            raise HyperliquidInfoError("l2Book returned a non-object payload")
        return data

    async def open_orders(self, user: str) -> list[dict[str, Any]]:
        data = await self._post_info({"type": "openOrders", "user": user})
        if not isinstance(data, list):
            raise HyperliquidInfoError("openOrders returned a non-list payload")
        return data

    async def frontend_open_orders(self, user: str) -> list[dict[str, Any]]:
        data = await self._post_info({"type": "frontendOpenOrders", "user": user})
        if not isinstance(data, list):
            raise HyperliquidInfoError("frontendOpenOrders returned a non-list payload")
        return data

    async def user_fills(self, user: str) -> list[dict[str, Any]]:
        data = await self._post_info({"type": "userFills", "user": user})
        if not isinstance(data, list):
            raise HyperliquidInfoError("userFills returned a non-list payload")
        if len(data) > MAX_USER_FILLS_PAGE_SIZE:
            raise HyperliquidInfoError("userFills exceeded the documented 2000 item limit")
        return data

    async def user_fills_by_time(
        self,
        user: str,
        start_time: int,
        end_time: int,
    ) -> list[dict[str, Any]]:
        payload = build_user_fills_by_time_payload(user, start_time, end_time)
        data = await self._post_info(payload)
        if not isinstance(data, list):
            raise HyperliquidInfoError("userFillsByTime returned a non-list payload")
        if len(data) > MAX_USER_FILLS_PAGE_SIZE:
            raise HyperliquidInfoError("userFillsByTime exceeded the documented 2000 item limit")
        return data

    async def iter_user_fills_by_time(
        self,
        user: str,
        start_time: int,
        end_time: int,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        cursor = start_time
        while cursor < end_time:
            page = await self.user_fills_by_time(user, cursor, end_time)
            yield page
            if len(page) < MAX_USER_FILLS_PAGE_SIZE:
                break
            page_times = [int(fill["time"]) for fill in page if "time" in fill]
            if not page_times:
                raise HyperliquidInfoError("Cannot paginate userFillsByTime without fill timestamps")
            next_cursor = max(page_times) + 1
            if next_cursor <= cursor:
                raise HyperliquidInfoError("userFillsByTime pagination cursor did not advance")
            cursor = next_cursor

    async def order_status(self, user: str, oid_or_cloid: int | str) -> OrderStatus:
        data = await self._post_info(
            {"type": "orderStatus", "user": user, "oid": oid_or_cloid},
        )
        if not isinstance(data, dict):
            raise HyperliquidInfoError("orderStatus returned a non-object payload")
        status_payload = data.get("order") if isinstance(data.get("order"), dict) else data
        return map_order_status(status_payload)

    async def candle_snapshot(
        self,
        coin: str,
        interval: str,
        start: int,
        end: int,
    ) -> list[dict[str, Any]]:
        if start >= end:
            raise ValueError("start must be strictly lower than end")
        data = await self._post_info(
            {
                "type": "candleSnapshot",
                "req": {
                    "coin": coin,
                    "interval": interval,
                    "startTime": int(start),
                    "endTime": int(end),
                },
            },
        )
        if not isinstance(data, list):
            raise HyperliquidInfoError("candleSnapshot returned a non-list payload")
        return data
