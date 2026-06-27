"""V14 #181 — Event recording (buffer/flush) + entry-window replay for backtest.

mlmodelpoly records `forceOrder`/decision events to a buffer and flushes them for replay.
This pure in-memory recorder buffers entry-context events, flushes them (e.g. to disk by the
caller), and slices a time window to replay the exact moments around an entry. No I/O here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class EntryEvent:
    ts_ms: int
    coin: str
    side: str
    kind: str               # e.g. "WHALE_FILL" | "LIQUIDATION" | "DECISION" | "BOOK"
    payload: dict[str, Any] = field(default_factory=dict)


class EntryEventRecorder:
    """Bounded ring buffer of entry-context events (idempotent on identical ts+kind+coin)."""

    def __init__(self, max_len: int = 10_000) -> None:
        self.max_len = int(max_len)
        self._events: list[EntryEvent] = []
        self._seen: set[tuple[int, str, str, str]] = set()

    def record(self, ev: EntryEvent) -> bool:
        key = (int(ev.ts_ms), str(ev.coin), str(ev.side), str(ev.kind))
        if key in self._seen:
            return False                      # dedupe
        self._events.append(ev)
        self._seen.add(key)
        if len(self._events) > self.max_len:  # drop oldest, keep bounded
            old = self._events.pop(0)
            self._seen.discard((int(old.ts_ms), str(old.coin), str(old.side), str(old.kind)))
        return True

    def __len__(self) -> int:
        return len(self._events)

    def flush(self) -> list[EntryEvent]:
        out = list(self._events)
        self._events.clear()
        self._seen.clear()
        return out

    def window(self, start_ms: int, end_ms: int, *, coin: str | None = None) -> list[EntryEvent]:
        lo, hi = int(start_ms), int(end_ms)
        c = (coin or "").upper() or None
        return [
            e for e in self._events
            if lo <= int(e.ts_ms) <= hi and (c is None or str(e.coin).upper() == c)
        ]


def replay_entry_windows(
    events: Sequence[EntryEvent],
    *,
    trigger_kind: str,
    pre_ms: int = 5_000,
    post_ms: int = 5_000,
) -> list[dict[str, Any]]:
    """For each trigger event, gather the events in [trigger-pre, trigger+post] for replay."""
    evs = sorted(events, key=lambda e: int(e.ts_ms))
    windows: list[dict[str, Any]] = []
    for trig in evs:
        if str(trig.kind) != trigger_kind:
            continue
        lo, hi = int(trig.ts_ms) - pre_ms, int(trig.ts_ms) + post_ms
        ctx = [e for e in evs if lo <= int(e.ts_ms) <= hi]
        windows.append({"trigger_ts_ms": int(trig.ts_ms), "coin": trig.coin, "side": trig.side, "events": ctx})
    return windows


__all__ = ["EntryEvent", "EntryEventRecorder", "replay_entry_windows"]
