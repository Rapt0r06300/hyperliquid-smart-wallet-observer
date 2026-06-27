"""Stale policy (V12, repo 05): block paper-ready signals on stale data / during refresh.

Honest gate: if the live data is older than max_age, or a full refresh is in progress, the
paper decision is NOT allowed to use it (deny-by-default). Pure / deterministic.
"""

from __future__ import annotations


def is_stale(last_update_ms: int | None, now_ms: int, *, max_age_ms: int = 15_000) -> bool:
    if last_update_ms is None:
        return True
    return (int(now_ms) - int(last_update_ms)) > int(max_age_ms)


def paper_blocked(*, last_update_ms: int | None, now_ms: int, refreshing: bool = False,
                  max_age_ms: int = 15_000) -> bool:
    return refreshing or is_stale(last_update_ms, now_ms, max_age_ms=max_age_ms)


__all__ = ["is_stale", "paper_blocked"]
