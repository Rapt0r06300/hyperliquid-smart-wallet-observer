"""Materialized cache (V12 capability R, repo 11): compute-once, reuse, bounded.

Memoizes expensive staged computations by key with hit/miss accounting. Pure.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable


class MaterializedCache:
    def __init__(self, *, max_entries: int = 1024) -> None:
        self._data: "OrderedDict[str, object]" = OrderedDict()
        self._max = max(1, int(max_entries))
        self.hits = 0
        self.misses = 0

    def get_or_compute(self, key: str, compute_fn: Callable[[], object]) -> object:
        if key in self._data:
            self.hits += 1
            self._data.move_to_end(key)
            return self._data[key]
        self.misses += 1
        value = compute_fn()
        self._data[key] = value
        if len(self._data) > self._max:
            self._data.popitem(last=False)
        return value

    def __len__(self) -> int:
        return len(self._data)


__all__ = ["MaterializedCache"]
