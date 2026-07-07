"""RawStore (V12 capability E — Fondation): idempotent raw-event store.

Stores raw fetched payloads with their hash + provenance link, deduplicated by
``raw_hash`` *within a RunContext*. This is the "RawStore + dedupe" capability:
replaying a backfill twice must yield zero duplicates, and LIVE / BACKTEST /
REPLAY / TEST_FIXTURE raw data must never be mixed (V12 §10 — never mix PnL or
data across contexts).

In-memory and deterministic (the SQLite-backed persistence is a separate, future
backend implementing the same contract). SAFETY: read-only research storage; it
records what was fetched (real data only), never fabricates, never places orders.
"""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field
from hashlib import sha256

from hl_observer.storage.run_context import RunContext


def compute_raw_hash(payload: object) -> str:
    """Stable SHA-256 of a payload (canonical JSON). Same payload -> same hash."""
    try:
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        blob = repr(payload)
    return sha256(blob.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RawEvent:
    source_id: str
    kind: str                       # endpoint or channel, e.g. "/info:allMids"
    raw_hash: str
    fetched_at_ms: int
    context: RunContext = RunContext.LIVE
    parsed_hash: str | None = None
    source_ts_ms: int | None = None
    item_count: int | None = None
    request_id: str | None = None
    payload: object | None = None   # kept small; large payloads should pass a ref

    @property
    def event_id(self) -> str:
        return f"{self.context.value}:{self.raw_hash[:16]}"


def make_raw_event(
    *,
    source_id: str,
    kind: str,
    payload: object,
    fetched_at_ms: int,
    context: RunContext = RunContext.LIVE,
    source_ts_ms: int | None = None,
    item_count: int | None = None,
    request_id: str | None = None,
    parsed_hash: str | None = None,
) -> RawEvent:
    """Build a RawEvent, computing ``raw_hash`` from the payload."""
    return RawEvent(
        source_id=source_id,
        kind=kind,
        raw_hash=compute_raw_hash(payload),
        fetched_at_ms=int(fetched_at_ms),
        context=context if isinstance(context, RunContext) else RunContext(str(context).upper()),
        parsed_hash=parsed_hash,
        source_ts_ms=source_ts_ms,
        item_count=item_count,
        request_id=request_id,
        payload=payload,
    )


class RawStore:
    def __init__(self, *, max_per_context: int = 50_000) -> None:
        self._max = max(1, max_per_context)
        # context -> ordered events; context -> set of seen raw_hashes
        self._events: dict[RunContext, deque[RawEvent]] = {}
        self._seen: dict[RunContext, set[str]] = {}

    def put(self, event: RawEvent) -> bool:
        """Store one raw event. Returns False if it's a duplicate (same hash, same context)."""
        ctx = event.context
        seen = self._seen.setdefault(ctx, set())
        if event.raw_hash in seen:
            return False
        seen.add(event.raw_hash)
        events = self._events.setdefault(ctx, deque(maxlen=self._max))
        if len(events) == self._max:  # evict oldest hash from the seen set too
            oldest = events[0]
            seen.discard(oldest.raw_hash)
        events.append(event)
        return True

    def get(self, raw_hash: str, *, context: RunContext = RunContext.LIVE) -> RawEvent | None:
        for ev in self._events.get(context, ()):  # small N in practice; linear ok
            if ev.raw_hash == raw_hash:
                return ev
        return None

    def count(self, *, context: RunContext | None = None) -> int:
        if context is not None:
            return len(self._events.get(context, ()))
        return sum(len(d) for d in self._events.values())

    def recent(self, *, source_id: str | None = None, context: RunContext = RunContext.LIVE, limit: int = 50) -> list[RawEvent]:
        out: list[RawEvent] = []
        for ev in reversed(self._events.get(context, ())):
            if source_id is None or ev.source_id == source_id:
                out.append(ev)
                if len(out) >= limit:
                    break
        return out

    def contexts(self) -> list[RunContext]:
        return [c for c in self._events if self._events[c]]


__all__ = ["RawEvent", "RawStore", "compute_raw_hash", "make_raw_event"]
