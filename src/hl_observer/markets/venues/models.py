"""Normalized public-market models for native external venues.

These models are intentionally read-only.  They describe public instruments,
BBO quotes and public market metrics; there is no account, auth or order model
in this package.
"""

from __future__ import annotations

from pydantic import BaseModel


class VenueInstrument(BaseModel):
    venue: str
    symbol: str
    base: str
    quote: str
    canonical_symbol: str
    status: str
    contract_type: str = "perpetual"
    is_prelaunch: bool = False
    tick_size: float | None = None
    min_size: float | None = None


class VenueQuote(BaseModel):
    venue: str
    symbol: str
    canonical_symbol: str
    bid_price: float
    bid_size: float
    ask_price: float
    ask_size: float
    exchange_ts_ms: int | None = None
    received_ts_ms: int
    sequence: int | None = None

    @property
    def mid_price(self) -> float:
        return (self.bid_price + self.ask_price) / 2.0

    @property
    def spread_bps(self) -> float:
        mid = self.mid_price
        if mid <= 0:
            return 0.0
        return (self.ask_price - self.bid_price) / mid * 10_000.0

    @property
    def age_ms(self) -> int | None:
        if self.exchange_ts_ms is None:
            return None
        return max(0, self.received_ts_ms - self.exchange_ts_ms)

    @property
    def is_crossed(self) -> bool:
        return self.bid_price > self.ask_price


class VenueMetrics(BaseModel):
    venue: str
    symbol: str
    canonical_symbol: str
    last_price: float | None = None
    mark_price: float | None = None
    index_price: float | None = None
    volume_24h: float | None = None
    turnover_24h: float | None = None
    open_interest: float | None = None
    open_interest_value: float | None = None
    funding_rate: float | None = None
    next_funding_time_ms: int | None = None
    exchange_ts_ms: int | None = None


class VenueHealth(BaseModel):
    venue: str
    connected: bool = False
    reconnects: int = 0
    last_message_ts_ms: int | None = None
    last_exchange_ts_ms: int | None = None
    last_error: str | None = None

    def stale_for_ms(self, now_ms: int) -> int | None:
        if self.last_message_ts_ms is None:
            return None
        return max(0, int(now_ms) - self.last_message_ts_ms)


__all__ = ["VenueHealth", "VenueInstrument", "VenueMetrics", "VenueQuote"]
