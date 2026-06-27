from __future__ import annotations


class DuplicateOrderGuard:
    def __init__(self) -> None:
        self._seen_signal_ids: set[str] = set()

    def check_and_mark(self, signal_id: str) -> bool:
        if signal_id in self._seen_signal_ids:
            return False
        self._seen_signal_ids.add(signal_id)
        return True
