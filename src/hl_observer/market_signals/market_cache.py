"""TTL market cache for fast paper decision paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class MarketCacheEntry:
    coin: str
    value: dict[str, Any]
    updated_at_ms: int
    ttl_ms: int

    def is_fresh(self, now_ms: int) -> bool:
        return int(now_ms) - int(self.updated_at_ms) <= int(self.ttl_ms)


class MarketCache:
    def __init__(self, *, ttl_ms: int = 1_000) -> None:
        self.ttl_ms = int(ttl_ms)
        self._entries: dict[str, MarketCacheEntry] = {}

    def set(self, coin: str, value: dict[str, Any], *, now_ms: int, ttl_ms: int | None = None) -> MarketCacheEntry:
        entry = MarketCacheEntry(
            coin=str(coin).upper(),
            value=dict(value),
            updated_at_ms=int(now_ms),
            ttl_ms=int(ttl_ms if ttl_ms is not None else self.ttl_ms),
        )
        self._entries[entry.coin] = entry
        return entry

    def get(self, coin: str, *, now_ms: int) -> dict[str, Any] | None:
        entry = self._entries.get(str(coin).upper())
        if entry is None or not entry.is_fresh(now_ms):
            return None
        return dict(entry.value)

    def status(self, *, now_ms: int) -> dict[str, object]:
        fresh = sum(1 for entry in self._entries.values() if entry.is_fresh(now_ms))
        return {"entries": len(self._entries), "fresh": fresh, "stale": len(self._entries) - fresh}


__all__ = ["MarketCache", "MarketCacheEntry"]
