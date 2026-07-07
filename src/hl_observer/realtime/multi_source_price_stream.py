"""Merge price events from multiple read-only sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class PriceEvent:
    source: str
    coin: str
    bid: float
    ask: float
    event_time_ms: int

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


def merge_price_events(events: Iterable[PriceEvent]) -> tuple[PriceEvent, ...]:
    return tuple(sorted(events, key=lambda event: (event.event_time_ms, event.source, event.coin)))


__all__ = ["PriceEvent", "merge_price_events"]
