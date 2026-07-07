from __future__ import annotations

from dataclasses import dataclass

from hl_observer.arbitrage.symbol_normalizer import normalize_symbol


@dataclass(frozen=True, slots=True)
class OrderBookSnapshot:
    source: str
    symbol: str
    bid: float
    ask: float
    bid_size: float = 0.0
    ask_size: float = 0.0
    timestamp_ms: int = 0

    @property
    def coin(self) -> str:
        return normalize_symbol(self.symbol)

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return max(self.bid, self.ask, 0.0)

    @property
    def spread_bps(self) -> float:
        if self.bid <= 0 or self.ask <= 0 or self.mid <= 0:
            return 0.0
        return (self.ask - self.bid) / self.mid * 10_000.0

    @property
    def depth_score(self) -> float:
        total = max(0.0, float(self.bid_size or 0.0)) + max(0.0, float(self.ask_size or 0.0))
        return max(0.0, min(1.0, total / 100_000.0))


__all__ = ["OrderBookSnapshot"]
