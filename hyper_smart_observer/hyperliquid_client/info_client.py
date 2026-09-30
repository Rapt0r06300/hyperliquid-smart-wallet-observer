from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.app.safety import SafetyViolation, sanitize_for_logs
from hyper_smart_observer.hyperliquid_client.payloads import info_payload, user_payload
from hyper_smart_observer.hyperliquid_client.rate_limiter import LocalRateLimiter
from hyper_smart_observer.hyperliquid_client.validation import normalize_wallet_address

LOG = logging.getLogger(__name__)
FORBIDDEN_PATH = "/" + "exchange"


class HttpResponse(Protocol):
    def raise_for_status(self) -> None: ...

    def json(self) -> Any: ...


class HttpClient(Protocol):
    def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
        timeout: float,
    ) -> HttpResponse: ...


class HyperliquidInfoError(RuntimeError):
    """Read-only Hyperliquid info client error."""


@dataclass(frozen=True)
class PaginationResult:
    fills: list[dict[str, Any]] = field(default_factory=list)
    pages_fetched: int = 0
    stopped_reason: str = "not_started"
    warnings: list[str] = field(default_factory=list)
    window_complete: bool = False
    truncated: bool = False
    oldest_available_ts: int | None = None
    aggregate_by_time_used: bool = False


class HyperliquidInfoClient:
    """Read-only Hyperliquid `/info` client.

    Network reads are disabled by configuration unless explicitly enabled.
    This client only posts JSON payloads to the computed info endpoint and
    refuses any configured URL containing the forbidden execution path.
    """

    def __init__(
        self,
        config: AppConfig,
        *,
        http_client: HttpClient | None = None,
        rate_limiter: LocalRateLimiter | None = None,
    ):
        self.config = config
        self.base_url = config.hyperliquid_info_base_url.rstrip("/")
        self.http_client = http_client or httpx.Client()
        self.rate_limiter = rate_limiter or LocalRateLimiter(config.info_min_request_interval_ms)

    @property
    def info_url(self) -> str:
        base = self.base_url
        if FORBIDDEN_PATH in base.lower():
            raise SafetyViolation("MAINNET_FORBIDDEN", "Forbidden execution endpoint configured.")
        if base.endswith("/info"):
            url = base
        else:
            url = f"{base}/info"
        if FORBIDDEN_PATH in url.lower() or not url.endswith("/info"):
            raise SafetyViolation("MAINNET_FORBIDDEN", "Only the read-only info endpoint is allowed.")
        return url

    def post_info(self, payload: dict[str, Any]) -> Any:
        if not self.config.enable_network_reads:
            raise SafetyViolation(
                "CONFIGURATION_REFUSED",
                "Network reads are disabled. Pass an explicit network-read flag.",
            )
        self._validate_payload(payload)
        url = self.info_url
        last_error: Exception | None = None
        for attempt in range(max(0, self.config.http_max_retries) + 1):
            self.rate_limiter.wait()
            try:
                LOG.debug("hyperliquid_info_request", extra={"payload": sanitize_for_logs(payload)})
                response = self.http_client.post(
                    url,
                    json=payload,
                    headers={"content-type": "application/json"},
                    timeout=self.config.http_timeout_seconds,
                )
                response.raise_for_status()
                return response.json()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = exc
                LOG.warning(
                    "hyperliquid_info_request_failed",
                    extra={"attempt": attempt + 1, "error": sanitize_for_logs(str(exc))},
                )
        raise HyperliquidInfoError(f"Hyperliquid info request failed: {last_error}") from last_error

    def get_meta(self) -> dict[str, Any]:
        response = self.post_info(info_payload("meta"))
        return _expect_dict(response, "meta")

    def get_all_mids(self) -> dict[str, Any]:
        response = self.post_info(info_payload("allMids"))
        return _expect_dict(response, "allMids")

    def get_l2_book(self, coin: str) -> dict[str, Any]:
        response = self.post_info(info_payload("l2Book", coin=str(coin).upper()))
        return _expect_dict(response, "l2Book")

    def get_candle_snapshot(
        self,
        coin: str,
        *,
        interval: str = "1m",
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
    ) -> list[dict[str, Any]]:
        req: dict[str, Any] = {"coin": str(coin).upper(), "interval": interval}
        if start_time_ms is not None:
            req["startTime"] = int(start_time_ms)
        if end_time_ms is not None:
            req["endTime"] = int(end_time_ms)
        response = self.post_info(info_payload("candleSnapshot", req=req))
        return _expect_list(response, "candleSnapshot")

    def get_clearinghouse_state(self, address: str) -> dict[str, Any]:
        response = self.post_info(user_payload("clearinghouseState", address))
        return _expect_dict(response, "clearinghouseState")

    def get_user_fills(self, address: str, *, aggregate_by_time: bool = False) -> list[dict[str, Any]]:
        payload = user_payload("userFills", address)
        if aggregate_by_time:
            payload["aggregateByTime"] = True
        response = self.post_info(payload)
        return _expect_list(response, "userFills")[: self.config.user_fills_recent_limit]

    def get_user_fills_by_time(
        self,
        address: str,
        start_time_ms: int,
        end_time_ms: int | None = None,
        *,
        aggregate_by_time: bool = False,
    ) -> list[dict[str, Any]]:
        payload = user_payload("userFillsByTime", address, startTime=int(start_time_ms))
        if end_time_ms is not None:
            payload["endTime"] = int(end_time_ms)
        if aggregate_by_time:
            payload["aggregateByTime"] = True
        response = self.post_info(payload)
        return _expect_list(response, "userFillsByTime")[: self.config.info_time_range_page_limit]

    def collect_user_fills_by_time_paginated(
        self,
        address: str,
        start_time_ms: int,
        end_time_ms: int,
        *,
        max_pages: int | None = None,
        aggregate_by_time: bool = False,
    ) -> PaginationResult:
        max_pages = max_pages if max_pages is not None else self.config.max_pages_per_wallet
        if max_pages <= 0:
            return PaginationResult(
                stopped_reason="max_pages_zero",
                truncated=True,
                aggregate_by_time_used=aggregate_by_time,
            )

        user = normalize_wallet_address(address)
        current_start = int(start_time_ms)
        all_fills: list[dict[str, Any]] = []
        warnings: list[str] = []
        pages = 0
        while pages < max_pages and current_start <= end_time_ms:
            page = self.get_user_fills_by_time(
                user,
                current_start,
                end_time_ms,
                aggregate_by_time=aggregate_by_time,
            )
            pages += 1
            if not page:
                return _pagination_result(
                    all_fills,
                    pages,
                    "empty_response",
                    warnings,
                    window_complete=True,
                    aggregate_by_time_used=aggregate_by_time,
                )
            all_fills.extend(page)
            if len(all_fills) >= self.config.max_fills_per_run:
                return _pagination_result(
                    all_fills[: self.config.max_fills_per_run],
                    pages,
                    "max_fills_reached",
                    warnings,
                    truncated=True,
                    aggregate_by_time_used=aggregate_by_time,
                )
            last_timestamp = _max_fill_timestamp(page)
            if last_timestamp is None:
                warnings.append("no_timestamp_in_page")
                return _pagination_result(
                    all_fills,
                    pages,
                    "timestamp_missing",
                    warnings,
                    aggregate_by_time_used=aggregate_by_time,
                )
            if last_timestamp <= current_start:
                warnings.append("timestamp_not_progressing")
                return _pagination_result(
                    all_fills,
                    pages,
                    "timestamp_not_progressing",
                    warnings,
                    truncated=True,
                    aggregate_by_time_used=aggregate_by_time,
                )
            current_start = last_timestamp + 1
        return _pagination_result(
            all_fills,
            pages,
            "max_pages_reached",
            warnings,
            truncated=True,
            aggregate_by_time_used=aggregate_by_time,
        )

    def get_open_orders(self, address: str) -> list[dict[str, Any]]:
        response = self.post_info(user_payload("openOrders", address))
        return _expect_list(response, "openOrders")

    def get_frontend_open_orders(self, address: str) -> list[dict[str, Any]]:
        response = self.post_info(user_payload("frontendOpenOrders", address))
        return _expect_list(response, "frontendOpenOrders")

    def get_order_status(self, address: str, oid: int | str) -> dict[str, Any]:
        response = self.post_info(user_payload("orderStatus", address, oid=oid))
        return _expect_dict(response, "orderStatus")

    def get_historical_orders(self, address: str) -> list[dict[str, Any]]:
        response = self.post_info(user_payload("historicalOrders", address))
        return _expect_list(response, "historicalOrders")

    def get_portfolio(self, address: str) -> dict[str, Any]:
        response = self.post_info(user_payload("portfolio", address))
        return _expect_dict(response, "portfolio")

    def get_user_fees(self, address: str) -> dict[str, Any]:
        response = self.post_info(user_payload("userFees", address))
        return _expect_dict(response, "userFees")

    def get_user_rate_limit(self, address: str) -> dict[str, Any]:
        response = self.post_info(user_payload("userRateLimit", address))
        return _expect_dict(response, "userRateLimit")

    def _validate_payload(self, payload: dict[str, Any]) -> None:
        request_type = payload.get("type")
        if not isinstance(request_type, str) or not request_type:
            raise HyperliquidInfoError("Info payload requires a non-empty type.")
        text = str(payload).lower()
        if FORBIDDEN_PATH in text or "signature" in text:
            raise SafetyViolation("CONFIGURATION_REFUSED", "Info payload contains forbidden execution data.")


def _expect_dict(response: Any, method: str) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise HyperliquidInfoError(f"{method} response must be an object.")
    return response


def _expect_list(response: Any, method: str) -> list[dict[str, Any]]:
    if not isinstance(response, list):
        raise HyperliquidInfoError(f"{method} response must be a list.")
    return [item for item in response if isinstance(item, dict)]


def _max_fill_timestamp(page: list[dict[str, Any]]) -> int | None:
    timestamps: list[int] = []
    for item in page:
        value = item.get("time") if "time" in item else item.get("timestamp")
        try:
            timestamps.append(int(value))
        except (TypeError, ValueError):
            continue
    return max(timestamps) if timestamps else None


def _oldest_fill_timestamp(fills: list[dict[str, Any]]) -> int | None:
    timestamps: list[int] = []
    for item in fills:
        value = item.get("time") if "time" in item else item.get("timestamp")
        try:
            timestamps.append(int(value))
        except (TypeError, ValueError):
            continue
    return min(timestamps) if timestamps else None


def _pagination_result(
    fills: list[dict[str, Any]],
    pages: int,
    stopped_reason: str,
    warnings: list[str],
    *,
    window_complete: bool = False,
    truncated: bool = False,
    aggregate_by_time_used: bool = False,
) -> PaginationResult:
    return PaginationResult(
        fills=fills,
        pages_fetched=pages,
        stopped_reason=stopped_reason,
        warnings=warnings,
        window_complete=window_complete,
        truncated=truncated,
        oldest_available_ts=_oldest_fill_timestamp(fills),
        aggregate_by_time_used=aggregate_by_time_used,
    )
