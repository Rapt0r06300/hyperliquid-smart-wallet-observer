from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from hl_observer.hyperliquid.rate_weights import (
    HYPERSMART_INFO_TIME_RANGE_PAGE_LIMIT,
    HYPERSMART_MAX_FILLS_PER_RUN,
    HYPERSMART_MAX_PAGES_PER_WALLET,
)


class UserFillsByTimeClient(Protocol):
    async def user_fills_by_time(self, user: str, start_time: int, end_time: int) -> list[dict]: ...


@dataclass(frozen=True, slots=True)
class BoundedPaginationResult:
    fills: list[dict]
    pages_fetched: int
    stopped_reason: str
    next_start_time: int | None = None
    warnings: tuple[str, ...] = field(default_factory=tuple)


async def fetch_user_fills_by_time_bounded(
    client: UserFillsByTimeClient,
    *,
    user: str,
    start_time: int,
    end_time: int,
    max_pages: int = HYPERSMART_MAX_PAGES_PER_WALLET,
    max_fills: int = HYPERSMART_MAX_FILLS_PER_RUN,
    page_limit: int = HYPERSMART_INFO_TIME_RANGE_PAGE_LIMIT,
) -> BoundedPaginationResult:
    """Read-only userFillsByTime pagination with explicit stopped_reason.

    startTime is inclusive. The next page starts at last_timestamp + 1. The loop
    is always bounded by max_pages and max_fills, and never invents fills.
    """

    if start_time >= end_time:
        return BoundedPaginationResult([], 0, "invalid_time_range", None, ("START_TIME_NOT_BEFORE_END_TIME",))
    if max_pages <= 0:
        return BoundedPaginationResult([], 0, "max_pages_zero")
    if max_fills <= 0:
        return BoundedPaginationResult([], 0, "max_fills_zero")

    cursor = int(start_time)
    pages = 0
    fills: list[dict] = []
    warnings: list[str] = []
    seen_page_hashes: set[str] = set()

    while cursor < end_time and pages < max_pages and len(fills) < max_fills:
        page = await client.user_fills_by_time(user, cursor, end_time)
        pages += 1
        if not page:
            return BoundedPaginationResult(fills, pages, "empty_response", cursor, tuple(warnings))
        page_hash = repr(page)
        if page_hash in seen_page_hashes:
            return BoundedPaginationResult(fills, pages, "duplicate_page", cursor, tuple(warnings))
        seen_page_hashes.add(page_hash)

        ordered = sorted(page, key=lambda item: _fill_time(item) or -1)
        if len(ordered) > page_limit:
            warnings.append(f"PAGE_LIMIT_TRUNCATED_TO_{page_limit}")
            ordered = ordered[:page_limit]

        accepted = 0
        for fill in ordered:
            if len(fills) >= max_fills:
                return BoundedPaginationResult(fills, pages, "max_fills_reached", cursor, tuple(warnings))
            fills.append(fill)
            accepted += 1

        if accepted == 0:
            return BoundedPaginationResult(fills, pages, "no_timestamped_items", cursor, tuple(warnings))
        last_timestamp = max((_fill_time(fill) for fill in ordered), default=None)
        if last_timestamp is None:
            return BoundedPaginationResult(fills, pages, "missing_timestamps", cursor, tuple(warnings))
        next_cursor = int(last_timestamp) + 1
        if next_cursor <= cursor:
            return BoundedPaginationResult(fills, pages, "timestamp_not_progressing", cursor, tuple(warnings))
        cursor = next_cursor

    if len(fills) >= max_fills:
        return BoundedPaginationResult(fills, pages, "max_fills_reached", cursor, tuple(warnings))
    if pages >= max_pages:
        return BoundedPaginationResult(fills, pages, "max_pages_reached", cursor, tuple(warnings))
    return BoundedPaginationResult(fills, pages, "completed", cursor, tuple(warnings))


def _fill_time(fill: dict) -> int | None:
    value = fill.get("time") or fill.get("timestamp") or fill.get("ts")
    try:
        return None if value is None else int(float(value))
    except (TypeError, ValueError):
        return None


__all__ = ["BoundedPaginationResult", "fetch_user_fills_by_time_bounded"]
