"""Book replay (V12 capability R, repo 11): reconstruct L2 state from orderbook deltas.

Feeds an initial snapshot then incremental deltas (price→size; size<=0 removes a level)
and exposes the reconstructed top-of-book at each step. Pure / deterministic, no network,
no fabrication: it only replays the deltas it is given, in order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BookState:
    ts_ms: int
    bids: tuple[tuple[float, float], ...]   # sorted by price desc
    asks: tuple[tuple[float, float], ...]   # sorted by price asc

    @property
    def best_bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread_bps(self) -> float | None:
        m = self.mid
        if m is None or m <= 0 or self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_ask - self.best_bid) / m * 10_000.0


class BookReplayer:
    def __init__(self) -> None:
        self._bids: dict[float, float] = {}
        self._asks: dict[float, float] = {}
        self._ts = 0

    def apply_snapshot(self, *, bids, asks, ts_ms: int) -> None:
        if isinstance(ts_ms, bool) or int(ts_ms) < self._ts:
            raise ValueError("book timestamps must be monotonic")
        def levels(rows):
            out = {}
            for price, size in rows:
                price_f, size_f = float(price), float(size)
                if (not math.isfinite(price_f) or not math.isfinite(size_f)
                        or price_f <= 0.0):
                    raise ValueError("book prices and sizes must be finite")
                if size_f > 0.0:
                    out[price_f] = size_f
            return out
        self._bids = levels(bids)
        self._asks = levels(asks)
        if self._bids and self._asks and max(self._bids) >= min(self._asks):
            raise ValueError("crossed order book snapshot")
        self._ts = int(ts_ms)

    def apply_delta(self, *, side: str, price: float, size: float, ts_ms: int) -> None:
        if isinstance(ts_ms, bool) or int(ts_ms) < self._ts:
            raise ValueError("book timestamps must be monotonic")
        side_l = str(side).lower()
        if side_l not in {"bid", "bids", "ask", "asks"}:
            raise ValueError("unsupported book side")
        book = self._bids if side_l.startswith("b") else self._asks
        price = float(price)
        size = float(size)
        if not math.isfinite(price) or not math.isfinite(size) or price <= 0.0:
            raise ValueError("book delta price and size must be finite")
        if size <= 0:
            book.pop(price, None)          # size 0 removes the level
        else:
            book[price] = size
        if self._bids and self._asks and max(self._bids) >= min(self._asks):
            raise ValueError("crossed order book delta")
        self._ts = int(ts_ms)

    def state(self) -> BookState:
        bids = tuple(sorted(self._bids.items(), key=lambda kv: -kv[0]))
        asks = tuple(sorted(self._asks.items(), key=lambda kv: kv[0]))
        return BookState(ts_ms=self._ts, bids=bids, asks=asks)


def replay_book(events: list[dict]) -> list[BookState]:
    """Replay a sequence of {type:'snapshot'|'delta', ...} events, returning state after each."""
    r = BookReplayer()
    out: list[BookState] = []
    for ev in events:
        if ev.get("type") == "snapshot":
            r.apply_snapshot(bids=ev.get("bids", []), asks=ev.get("asks", []), ts_ms=int(ev.get("ts_ms", 0)))
        else:
            r.apply_delta(side=ev.get("side", "bid"), price=ev.get("price", 0.0),
                          size=ev.get("size", 0.0), ts_ms=int(ev.get("ts_ms", 0)))
        out.append(r.state())
    return out


__all__ = ["BookState", "BookReplayer", "replay_book"]
