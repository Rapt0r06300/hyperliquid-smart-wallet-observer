"""Byte- and count-bounded FIFO for raw market-data envelopes.

The byte gauge is a conservative estimate (serialized payload plus envelope
overhead), not a process-RSS measurement. Evictions are always reported to the
caller so it can mark the corresponding feed degraded.
"""
from __future__ import annotations

import json
import sys
from collections import deque
from typing import Any, Callable

DEFAULT_MAX_ITEMS = 100_000
DEFAULT_MAX_ESTIMATED_BYTES = 256 * 1024 * 1024
DEFAULT_ENTRY_OVERHEAD_BYTES = 4_096


def estimate_tick_envelope_bytes(envelope: Any) -> int:
    """Return a cheap retained-size estimate for a queued event."""
    payload = envelope.raw_payload
    if isinstance(payload, (bytes, str)):
        payload_bytes = sys.getsizeof(payload)
    else:
        payload_bytes = sys.getsizeof(json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"), default=str
        ))
    provenance = getattr(envelope, "provenance", {}) or {}
    parsed_summary = getattr(envelope, "parsed_summary", {}) or {}
    metadata_bytes = (
        sys.getsizeof(provenance) + sys.getsizeof(parsed_summary)
        + 128 * (len(provenance) + len(parsed_summary))
    )
    return DEFAULT_ENTRY_OVERHEAD_BYTES + payload_bytes + metadata_bytes


class BoundedTickEnvelopeQueue:
    """FIFO bounded by event count and estimated bytes, with explicit eviction."""

    def __init__(
        self,
        *,
        max_items: int = DEFAULT_MAX_ITEMS,
        max_estimated_bytes: int = DEFAULT_MAX_ESTIMATED_BYTES,
    ) -> None:
        if max_items < 1 or max_estimated_bytes < 1:
            raise ValueError("queue bounds must be positive")
        self.max_items = int(max_items)
        self.max_estimated_bytes = int(max_estimated_bytes)
        self._items: deque[tuple[Any, int]] = deque()
        self.estimated_bytes = 0

    def __len__(self) -> int:
        return len(self._items)

    def append(self, envelope: Any, *, on_drop: Callable[[Any], None]) -> bool:
        size = estimate_tick_envelope_bytes(envelope)
        if size > self.max_estimated_bytes:
            on_drop(envelope)
            return False
        while self._items and (
            len(self._items) >= self.max_items
            or self.estimated_bytes + size > self.max_estimated_bytes
        ):
            dropped, dropped_size = self._items.popleft()
            self.estimated_bytes -= dropped_size
            on_drop(dropped)
        self._items.append((envelope, size))
        self.estimated_bytes += size
        return True

    def pop_batch(self, *, max_items: int, max_estimated_bytes: int) -> list[Any]:
        if max_items < 1 or max_estimated_bytes < 1:
            raise ValueError("batch bounds must be positive")
        batch: list[Any] = []
        batch_bytes = 0
        while self._items and len(batch) < max_items:
            envelope, size = self._items[0]
            if batch and batch_bytes + size > max_estimated_bytes:
                break
            self._items.popleft()
            self.estimated_bytes -= size
            batch.append(envelope)
            batch_bytes += size
        return batch


__all__ = [
    "BoundedTickEnvelopeQueue",
    "DEFAULT_MAX_ITEMS",
    "DEFAULT_MAX_ESTIMATED_BYTES",
    "estimate_tick_envelope_bytes",
]
