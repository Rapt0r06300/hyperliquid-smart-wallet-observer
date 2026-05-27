from __future__ import annotations


class EventDedupe:
    def __init__(self, max_keys: int = 10_000) -> None:
        self.max_keys = max_keys
        self._seen: list[str] = []
        self._set: set[str] = set()

    def is_duplicate(self, key: str) -> bool:
        if key in self._set:
            return True
        self._seen.append(key)
        self._set.add(key)
        if len(self._seen) > self.max_keys:
            old = self._seen.pop(0)
            self._set.discard(old)
        return False

    def seen(self, key: str) -> bool:
        return self.is_duplicate(key)
