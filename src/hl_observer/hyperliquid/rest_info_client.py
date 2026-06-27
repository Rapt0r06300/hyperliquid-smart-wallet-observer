from __future__ import annotations

import asyncio
import hashlib
import json
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
    "meta",
    "activeAssetCtx",
    "allMids",
    "l2Book",
    "clearinghouseState",
    "openOrders",
    "frontendOpenOrders",
    "userFills",
    "userFillsByTime",
    "orderStatus",
    "candleSnapshot",
    "portfolio",
    "historicalOrders",
    "userFunding",
    "userRateLimit",
}


class HyperliquidInfoError(RuntimeError):
    """Raised when a read-only Hyperliquid info call fails."""


def _ensure_read_only_payload(payload: dict[str, Any]) -> None:
    request_type = payload.get("type")
    if request_type not in READ_ONLY_INFO_TYPES:
        raise HyperliquidInfoError(f"Unsupported read-only info type: {request_type!r}")


def stable_json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_all_mids_payload() -> dict[str, Any]:
    return {"type": "allMids"}


def build_meta_payload() -> dict[str, Any]:
    return {"type": "meta"}


def build_active_asset_ctx_payload(coin: str) -> dict[str, Any]:
    return {"type": "activeAssetCtx", "coin": coin.upper()}


def build_l2_book_payload(coin: str) -> dict[str, Any]:
    return {"type": "l2Book", "coin": coin.upper()}


def build_open_orders_payload(user: str) -> dict[str, Any]:
    return {"type": "openOrders", "user": user}


def build_clearinghouse_state_payload(user: str) -> dict[str, Any]:
    return {"type": "clearinghouseState", "user": user}


def build_frontend_open_orders_payload(user: str) -> dict[str, Any]:
    return {"type": "frontendOpenOrders", "user": user}


def build_user_fills_payload(user: str, aggregate_by_time: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "userFills", "user": user}
    if aggregate_by_time:
        payload["aggregateByTime"] = True
    return payload


def build_user_fills_by_time_payload(
    user: str,
    start_time: int,
    end_time: int,
    aggregate_by_time: bool = False,
) -> dict[str, Any]:
    if start_time >= end_time:
        raise ValueError("start_time must be strictly lower than end_time")
    payload: dict[str, Any] = {
        "type": "userFillsByTime",
        "user": user,
        "startTime": int(start_time),
        "endTime": int(end_time),
    }
    if aggregate_by_time:
        payload["aggregateByTime"] = True
    return payload


def build_order_status_payload(user: str, oid_or_cloid: int | str) -> dict[str, Any]:
    return {"type": "orderStatus", "user": user, "oid": oid_or_cloid}


def build_portfolio_payload(user: str) -> dict[str, Any]:
    return {"type": "portfolio", "user": user}


def build_historical_orders_payload(user: str) -> dict[str, Any]:
    return {"type": "historicalOrders", "user": user}


def build_user_funding_payload(user: str, start_time: int | None = None, end_time: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"type": "userFunding", "user": user}
    if start_time is not None:
        payload["startTime"] = int(start_time)
    if end_time is not None:
        payload["endTime"] = int(end_time)
    return payload


def build_user_rate_limit_payload(user: str) -> dict[str, Any]:
    return {"type": "userRateLimit", "user": user}


def build_candle_snapshot_payload(
    coin: str,
    interval: str,
    start_time: int,
    end_time: int,
) -> dict[str, Any]:
    if start_time >= end_time:
        raise ValueError("start_time must be strictly lower than end_time")
    return {
        "type": "candleSnapshot",
        "req": {
            "coin": coin.upper(),
            "interval": interval,
            "startTime": int(start_time),
            "endTime": int(end_time),
        },
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
        recorder: "CollectionRecorder | None" = None,
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
        # Optional, opt-in provenance recorder (V12 A+E). Best-effort: never breaks fetches.
        self._recorder = recorder

    async def __aenter__(self) -> HyperliquidInfoClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout_seconds)
            self._owns_client = True
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()

    async def _post_info(self, request_type: str, payload: dict[str, Any] | None = None) -> Any:
        payload = {"type": request_type, **(payload or {})}
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
                data = response.json()
                self._record_fetch(request_type, data, ok=True, error=None)
                return data
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                await asyncio.sleep(self.backoff_base_seconds * (2**attempt))
        self._record_fetch(request_type, None, ok=False, error=str(last_error))
        raise HyperliquidInfoError(f"Hyperliquid /info call failed: {last_error}") from last_error

    def _record_fetch(self, request_type: str, response: object, *, ok: bool, error: str | None) -> None:
        """Forward one fetch to the optional provenance recorder. Never raises."""
        recorder = getattr(self, "_recorder", None)
        if recorder is None:
            return
        try:
            recorder.record_rest(request_type=request_type, response=response, ok=ok, error=error)
        except Exception:
            pass

    async def all_mids(self) -> dict[str, str]:
        data = await self._post_info("allMids")
        if not isinstance(data, dict):
            raise HyperliquidInfoError("allMids returned a non-object payload")
        return data

    async def meta(self) -> dict[str, Any]:
        data = await self._post_info("meta")
        if not isinstance(data, dict):
            raise HyperliquidInfoError("meta returned a non-object payload")
        return data

    async def active_asset_ctx(self, coin: str) -> dict[str, Any]:
        data = await self._post_info("activeAssetCtx", {"coin": coin.upper()})
        if not isinstance(data, dict):
            raise HyperliquidInfoError("activeAssetCtx returned a non-object payload")
        return data

    async def l2_book(self, coin: str) -> dict[str, Any]:
        data = await self._post_info("l2Book", {"coin": coin.upper()})
        if not isinstance(data, dict):
            raise HyperliquidInfoError("l2Book returned a non-object payload")
        return data

    async def open_orders(self, user: str) -> list[dict[str, Any]]:
        data = await self._post_info("openOrders", {"user": user})
        if not isinstance(data, list):
            raise HyperliquidInfoError("openOrders returned a non-list payload")
        return data

    async def clearinghouse_state(self, user: str) -> dict[str, Any]:
        data = await self._post_info("clearinghouseState", {"user": user})
        if not isinstance(data, dict):
            raise HyperliquidInfoError("clearinghouseState returned a non-object payload")
        return data

    async def frontend_open_orders(self, user: str) -> list[dict[str, Any]]:
        data = await self._post_info("frontendOpenOrders", {"user": user})
        if not isinstance(data, list):
            raise HyperliquidInfoError("frontendOpenOrders returned a non-list payload")
        return data

    async def user_fills(
        self,
        user: str,
        aggregate_by_time: bool = False,
    ) -> list[dict[str, Any]]:
        payload = {"user": user}
        if aggregate_by_time:
            payload["aggregateByTime"] = True
        data = await self._post_info("userFills", payload)
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
        aggregate_by_time: bool = False,
    ) -> list[dict[str, Any]]:
        payload = build_user_fills_by_time_payload(
            user,
            start_time,
            end_time,
            aggregate_by_time=aggregate_by_time,
        )
        request_payload = {key: value for key, value in payload.items() if key != "type"}
        data = await self._post_info("userFillsByTime", request_payload)
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
        page_window_ms: int | None = None,
        max_pages: int | None = None,
        aggregate_by_time: bool = False,
    ) -> AsyncIterator[list[dict[str, Any]]]:
        cursor = start_time
        pages_seen = 0
        seen_page_hashes: set[str] = set()
        while cursor < end_time:
            if max_pages is not None and pages_seen >= max_pages:
                break
            request_end = min(end_time, cursor + page_window_ms) if page_window_ms else end_time
            if request_end <= cursor:
                raise HyperliquidInfoError("userFillsByTime pagination window did not advance")
            page = await self.user_fills_by_time(
                user,
                cursor,
                request_end,
                aggregate_by_time=aggregate_by_time,
            )
            if not page:
                break
            page_hash = stable_json_hash(page)
            if page_hash in seen_page_hashes:
                raise HyperliquidInfoError("Duplicate userFillsByTime page detected")
            seen_page_hashes.add(page_hash)
            pages_seen += 1
            yield page
            if page_window_ms and len(page) < MAX_USER_FILLS_PAGE_SIZE:
                cursor = request_end + 1
                continue
            if not page_window_ms and len(page) < MAX_USER_FILLS_PAGE_SIZE:
                break
            page_times = [int(fill["time"]) for fill in page if "time" in fill]
            if not page_times:
                raise HyperliquidInfoError("Cannot paginate userFillsByTime without fill timestamps")
            next_cursor = max(page_times) + 1
            if next_cursor <= cursor:
                raise HyperliquidInfoError("userFillsByTime pagination cursor did not advance")
            cursor = next_cursor

    async def order_status(self, user: str, oid_or_cloid: int | str) -> OrderStatus:
        data = await self._post_info("orderStatus", {"user": user, "oid": oid_or_cloid})
        if not isinstance(data, dict):
            raise HyperliquidInfoError("orderStatus returned a non-object payload")
        status_payload = data.get("order") if isinstance(data.get("order"), dict) else data
        return map_order_status(status_payload)

    async def portfolio(self, user: str) -> Any:
        return await self._post_info("portfolio", {"user": user})

    async def historical_orders(self, user: str) -> list[dict[str, Any]]:
        data = await self._post_info("historicalOrders", {"user": user})
        if not isinstance(data, list):
            raise HyperliquidInfoError("historicalOrders returned a non-list payload")
        return data

    async def user_funding(
        self,
        user: str,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> list[dict[str, Any]]:
        request = build_user_funding_payload(user, start_time=start_time, end_time=end_time)
        payload = {key: value for key, value in request.items() if key != "type"}
        data = await self._post_info("userFunding", payload)
        if not isinstance(data, list):
            raise HyperliquidInfoError("userFunding returned a non-list payload")
        return data

    async def user_rate_limit(self, user: str) -> dict[str, Any]:
        data = await self._post_info("userRateLimit", {"user": user})
        if not isinstance(data, dict):
            raise HyperliquidInfoError("userRateLimit returned a non-object payload")
        return data

    async def candle_snapshot(
        self,
        coin: str,
        interval: str,
        start_time: int,
        end_time: int,
    ) -> list[dict[str, Any]]:
        payload = build_candle_snapshot_payload(
            coin,
            interval,
            start_time,
            end_time,
        )
        data = await self._post_info("candleSnapshot", {"req": payload["req"]})
        if not isinstance(data, list):
            raise HyperliquidInfoError("candleSnapshot returned a non-list payload")
        return data
