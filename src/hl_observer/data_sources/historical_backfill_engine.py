from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
try:
    from enum import StrEnum
except ImportError:
    from enum import Enum
    class StrEnum(str, Enum): pass
from typing import Any

from hl_observer.data_sources.acquisition_engine import (
    DataQualityAssessment,
    DataQualityConfig,
    DataQualityGate,
    FetchRequest,
    FetchResult,
    RequestBudgetManager,
)


INFO_TIME_RANGE_PAGE_LIMIT = 500
USER_FILLS_RECENT_LIMIT = 2_000
USER_FILLS_BY_TIME_MAX_RECENT = 10_000


class BackfillStopReason(StrEnum):
    COMPLETED = "COMPLETED"
    EMPTY_RESPONSE = "EMPTY_RESPONSE"
    MAX_PAGES_REACHED = "MAX_PAGES_REACHED"
    MAX_FILLS_REACHED = "MAX_FILLS_REACHED"
    TIMESTAMP_NOT_PROGRESSING = "TIMESTAMP_NOT_PROGRESSING"
    RATE_LIMIT_GUARD = "RATE_LIMIT_GUARD"
    NETWORK_READ_DISABLED = "NETWORK_READ_DISABLED"
    PAGE_QUALITY_REJECTED = "PAGE_QUALITY_REJECTED"
    DUPLICATE_PAGE = "DUPLICATE_PAGE"
    FETCH_ERROR = "FETCH_ERROR"


@dataclass(frozen=True, slots=True)
class BackoffPolicy:
    base_delay_ms: int = 250
    max_delay_ms: int = 5_000
    multiplier: float = 2.0

    def delay_for_attempt(self, attempt: int) -> int:
        attempt = max(0, int(attempt))
        return min(self.max_delay_ms, int(self.base_delay_ms * (self.multiplier**attempt)))


@dataclass(frozen=True, slots=True)
class CacheEntry:
    payload: list[dict[str, Any]]
    stored_at_ms: int
    ttl_ms: int

    def is_fresh(self, now_ms: int) -> bool:
        return now_ms - self.stored_at_ms <= self.ttl_ms


@dataclass(slots=True)
class TtlPageCache:
    ttl_ms: int = 30_000
    _entries: dict[str, CacheEntry] = field(default_factory=dict)

    def get(self, key: str, *, now_ms: int) -> list[dict[str, Any]] | None:
        entry = self._entries.get(key)
        if entry is None or not entry.is_fresh(now_ms):
            return None
        return list(entry.payload)

    def put(self, key: str, payload: list[dict[str, Any]], *, now_ms: int) -> None:
        self._entries[key] = CacheEntry(list(payload), now_ms, self.ttl_ms)


@dataclass(frozen=True, slots=True)
class HistoricalBackfillConfig:
    max_pages_per_wallet: int = 5
    max_fills_per_wallet: int = USER_FILLS_BY_TIME_MAX_RECENT
    page_window_ms: int = 86_400_000
    request_weight_per_page: int = 1
    max_retries: int = 2
    aggregate_by_time: bool = False
    cache_ttl_ms: int = 30_000


@dataclass(frozen=True, slots=True)
class BackfillPage:
    request_id: str
    wallet_address: str
    start_time_ms: int
    end_time_ms: int
    fills: tuple[dict[str, Any], ...]
    source: str
    payload_hash: str
    cache_hit: bool
    quality: DataQualityAssessment


@dataclass(frozen=True, slots=True)
class HistoricalBackfillResult:
    wallet_address: str
    start_time_ms: int
    end_time_ms: int
    pages: tuple[BackfillPage, ...]
    fills: tuple[dict[str, Any], ...]
    pages_fetched: int
    cache_hits: int
    stopped_reason: BackfillStopReason
    next_cursor_ms: int
    warnings: tuple[str, ...] = ()
    backoff_delays_ms: tuple[int, ...] = ()


FetchPage = Callable[[str, int, int, bool], Awaitable[list[dict[str, Any]]]]
SleepFunc = Callable[[float], Awaitable[None]]


class HistoricalBackfillEngine:
    def __init__(
        self,
        *,
        fetch_page: FetchPage,
        budget: RequestBudgetManager,
        quality_gate: DataQualityGate | None = None,
        cache: TtlPageCache | None = None,
        backoff: BackoffPolicy | None = None,
        sleep: SleepFunc | None = None,
        config: HistoricalBackfillConfig | None = None,
    ) -> None:
        self.fetch_page = fetch_page
        self.budget = budget
        self.quality_gate = quality_gate or DataQualityGate(
            DataQualityConfig(
                max_data_age_ms=10 * 365 * 24 * 60 * 60 * 1000,
                max_transport_latency_ms=10_000,
                min_source_confidence_score=0.70,
            )
        )
        self.cache = cache or TtlPageCache()
        self.backoff = backoff or BackoffPolicy()
        self.sleep = sleep or asyncio.sleep
        self.config = config or HistoricalBackfillConfig()

    async def run_user_fills_by_time(
        self,
        *,
        wallet_address: str,
        start_time_ms: int,
        end_time_ms: int,
        now_ms: int,
    ) -> HistoricalBackfillResult:
        cursor = max(0, int(start_time_ms))
        end_time_ms = max(cursor, int(end_time_ms))
        pages: list[BackfillPage] = []
        fills: list[dict[str, Any]] = []
        warnings: list[str] = []
        backoff_delays: list[int] = []
        seen_page_hashes: set[str] = set()
        cache_hits = 0
        stopped_reason = BackfillStopReason.COMPLETED

        while cursor < end_time_ms:
            if len(pages) >= self.config.max_pages_per_wallet:
                stopped_reason = BackfillStopReason.MAX_PAGES_REACHED
                break
            if len(fills) >= self.config.max_fills_per_wallet:
                stopped_reason = BackfillStopReason.MAX_FILLS_REACHED
                break

            page_end = min(end_time_ms, cursor + max(1, self.config.page_window_ms))
            request = FetchRequest(
                request_id=f"userFillsByTime:{wallet_address}:{cursor}:{page_end}",
                provider_name="OfficialInfoProvider",
                endpoint="/info",
                request_type="userFillsByTime",
                wallet_address=wallet_address,
                weight=max(1, self.config.request_weight_per_page),
                created_at_ms=now_ms,
                ttl_ms=self.config.cache_ttl_ms,
                metadata={"startTime": cursor, "endTime": page_end},
            )
            cache_key = request.dedupe_key
            cached = self.cache.get(cache_key, now_ms=now_ms)
            if cached is not None:
                cache_hits += 1
                page_payload = cached
                source = "cache"
            else:
                budget_decision = self.budget.reserve(request)
                if not budget_decision.allowed:
                    stopped_reason = (
                        BackfillStopReason.NETWORK_READ_DISABLED
                        if budget_decision.reason == "NETWORK_READ_DISABLED"
                        else BackfillStopReason.RATE_LIMIT_GUARD
                    )
                    warnings.append(budget_decision.reason)
                    break
                page_payload = await self._fetch_with_backoff(
                    wallet_address,
                    cursor,
                    page_end,
                    warnings=warnings,
                    backoff_delays=backoff_delays,
                )
                if page_payload is None:
                    stopped_reason = BackfillStopReason.FETCH_ERROR
                    break
                self.cache.put(cache_key, page_payload, now_ms=now_ms)
                source = "network_read_only"

            page_hash = _stable_hash(page_payload)
            if page_hash in seen_page_hashes:
                stopped_reason = BackfillStopReason.DUPLICATE_PAGE
                warnings.append("DUPLICATE_PAGE")
                break
            seen_page_hashes.add(page_hash)

            if not page_payload:
                stopped_reason = BackfillStopReason.EMPTY_RESPONSE
                break

            exchange_ts = _page_exchange_ts(page_payload)
            quality = self.quality_gate.assess(
                FetchResult(
                    request=request,
                    success=True,
                    payload=page_payload,
                    fetched_at_ms=now_ms,
                    local_received_at_ms=now_ms,
                    exchange_ts_ms=exchange_ts,
                    source_confidence_score=0.95 if source == "network_read_only" else 0.90,
                    transport_latency_ms=0,
                    source_url="https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint",
                ),
                now_ms=now_ms,
                proves_pnl=True,
            )
            if not quality.accepted_for_simulation:
                stopped_reason = BackfillStopReason.PAGE_QUALITY_REJECTED
                warnings.extend(quality.reasons)
                break

            pages.append(
                BackfillPage(
                    request_id=request.request_id,
                    wallet_address=wallet_address,
                    start_time_ms=cursor,
                    end_time_ms=page_end,
                    fills=tuple(page_payload),
                    source=source,
                    payload_hash=page_hash,
                    cache_hit=source == "cache",
                    quality=quality,
                )
            )
            fills.extend(page_payload)
            if len(fills) >= self.config.max_fills_per_wallet:
                stopped_reason = BackfillStopReason.MAX_FILLS_REACHED
                break

            next_cursor = _next_cursor(cursor, page_payload, page_end)
            if next_cursor <= cursor:
                stopped_reason = BackfillStopReason.TIMESTAMP_NOT_PROGRESSING
                warnings.append("TIMESTAMP_NOT_PROGRESSING")
                break
            cursor = next_cursor

        return HistoricalBackfillResult(
            wallet_address=wallet_address,
            start_time_ms=start_time_ms,
            end_time_ms=end_time_ms,
            pages=tuple(pages),
            fills=tuple(fills[: self.config.max_fills_per_wallet]),
            pages_fetched=len(pages),
            cache_hits=cache_hits,
            stopped_reason=stopped_reason,
            next_cursor_ms=cursor,
            warnings=tuple(sorted(set(warnings))),
            backoff_delays_ms=tuple(backoff_delays),
        )

    async def _fetch_with_backoff(
        self,
        wallet_address: str,
        start_time_ms: int,
        end_time_ms: int,
        *,
        warnings: list[str],
        backoff_delays: list[int],
    ) -> list[dict[str, Any]] | None:
        for attempt in range(self.config.max_retries + 1):
            try:
                page = await self.fetch_page(wallet_address, start_time_ms, end_time_ms, self.config.aggregate_by_time)
                if not isinstance(page, list):
                    warnings.append("API_RESPONSE_INVALID")
                    return None
                return page
            except Exception as exc:  # noqa: BLE001 - fetcher is adapter/user supplied.
                warnings.append(f"FETCH_ERROR:{type(exc).__name__}")
                if attempt >= self.config.max_retries:
                    return None
                delay_ms = self.backoff.delay_for_attempt(attempt)
                backoff_delays.append(delay_ms)
                await self.sleep(delay_ms / 1000.0)
        return None


def format_historical_backfill_result(result: HistoricalBackfillResult) -> str:
    return "\n".join(
        [
            "historical_backfill=read_only_bounded",
            f"wallet={result.wallet_address}",
            f"window={result.start_time_ms}->{result.end_time_ms}",
            f"pages_fetched={result.pages_fetched}",
            f"fills={len(result.fills)}",
            f"cache_hits={result.cache_hits}",
            f"stopped_reason={result.stopped_reason.value}",
            f"next_cursor_ms={result.next_cursor_ms}",
            f"warnings={','.join(result.warnings) if result.warnings else 'OK'}",
            f"backoff_delays_ms={','.join(str(item) for item in result.backoff_delays_ms) if result.backoff_delays_ms else 'none'}",
            "execution=forbidden",
            "profit_guarantee=false",
        ]
    )


def _stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _page_exchange_ts(page: list[dict[str, Any]]) -> int | None:
    times = [int(item["time"]) for item in page if isinstance(item, dict) and "time" in item]
    return max(times) if times else None


def _next_cursor(cursor: int, page: list[dict[str, Any]], page_end: int) -> int:
    times = [int(item["time"]) for item in page if isinstance(item, dict) and "time" in item]
    if not times:
        return cursor
    max_time = max(times)
    if len(page) < USER_FILLS_RECENT_LIMIT:
        return max(max_time + 1, page_end + 1)
    return max_time + 1
