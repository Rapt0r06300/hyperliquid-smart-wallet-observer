"""Data bus (V12 capability R, repo 11): unified read-only tiered data access.

Tries tiers in order — in-memory cache -> local store -> archive -> API — and caches the
first hit. Read-only research access; no order, no fabrication. The actual tier callables
are injected (e.g. SQLite reader, archive reader, HL /info client).
"""

from __future__ import annotations

from collections.abc import Callable


class DataBus:
    def __init__(
        self,
        *,
        local: Callable[[str], object | None] | None = None,
        archive: Callable[[str], object | None] | None = None,
        api: Callable[[str], object | None] | None = None,
    ) -> None:
        self._cache: dict[str, object] = {}
        self._local = local
        self._archive = archive
        self._api = api
        self.hits: dict[str, int] = {"cache": 0, "local": 0, "archive": 0, "api": 0, "miss": 0}

    def get(self, key: str) -> object | None:
        if key in self._cache:
            self.hits["cache"] += 1
            return self._cache[key]
        for tier_name, tier in (("local", self._local), ("archive", self._archive), ("api", self._api)):
            if tier is None:
                continue
            value = tier(key)
            if value is not None:
                self.hits[tier_name] += 1
                self._cache[key] = value
                return value
        self.hits["miss"] += 1
        return None

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._cache.clear()
        else:
            self._cache.pop(key, None)


__all__ = ["DataBus"]
