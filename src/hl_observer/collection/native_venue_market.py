"""Canonical read-only market data shared by native venue adapters.

This module is deliberately network-free: collectors normalize public market data
into :class:`NativeMarketSnapshot`, then Cross-Venue and Lead-Lag consume the same
freshness-gated store.  No order/exchange endpoint lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations
import math
import time
from typing import Iterable

from hl_observer.arbitrage.cross_source_comparator import CrossSourcePrice

SCHEMA_VERSION = "alina.native_venue_market.v1"
EXPLOITABLE = "EXPLOITABLE"
STALE = "STALE"
DESYNC = "DESYNC"
UNMEASURABLE = "UNMEASURABLE"

_STABLE_QUOTES = ("USDT", "USDC", "USD")


def canonical_coin(symbol: str) -> str:
    """Return a base-asset key shared by HL/Binance/Bybit/OKX perpetuals."""
    value = str(symbol or "").strip().upper()
    if not value:
        return ""
    if "-" in value:
        parts = [part for part in value.split("-") if part]
        if parts:
            return parts[0]
    for suffix in ("USDT-PERP", "USDC-PERP", "USD-PERP", "USDT", "USDC", "USD"):
        if value.endswith(suffix) and len(value) > len(suffix):
            return value[: -len(suffix)]
    return value


def _finite_positive(value: float | int | str | None) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and parsed > 0.0 else None


@dataclass(frozen=True, slots=True)
class MarketLevel:
    price: float
    size: float


@dataclass(frozen=True, slots=True)
class NativeMarketSnapshot:
    venue: str
    coin: str
    exchange_symbol: str
    bid: float
    ask: float
    exchange_ts_ms: int
    receive_ts_ms: int
    quality: str
    bids: tuple[MarketLevel, ...] = ()
    asks: tuple[MarketLevel, ...] = ()
    last: float | None = None
    mark: float | None = None
    index: float | None = None
    volume_24h: float | None = None
    open_interest: float | None = None
    funding_rate: float | None = None
    funding_interval_hours: float | None = None
    sequence: int | None = None
    reason: str = ""
    real_execution: bool = False

    @classmethod
    def build(
        cls,
        *,
        venue: str,
        coin: str,
        exchange_symbol: str,
        bid: float,
        ask: float,
        exchange_ts_ms: int,
        receive_ts_ms: int,
        now_ms: int | None = None,
        stale_after_ms: int = 1_000,
        quality: str | None = None,
        bids: Iterable[MarketLevel] = (),
        asks: Iterable[MarketLevel] = (),
        last: float | None = None,
        mark: float | None = None,
        index: float | None = None,
        volume_24h: float | None = None,
        open_interest: float | None = None,
        funding_rate: float | None = None,
        funding_interval_hours: float | None = None,
        sequence: int | None = None,
        reason: str = "",
    ) -> "NativeMarketSnapshot":
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        bid_f = _finite_positive(bid)
        ask_f = _finite_positive(ask)
        derived_quality = quality
        derived_reason = reason
        if derived_quality is None:
            if bid_f is None or ask_f is None or ask_f < bid_f:
                derived_quality = UNMEASURABLE
                derived_reason = derived_reason or "INVALID_BBO"
            elif max(0, now - int(receive_ts_ms)) > int(stale_after_ms):
                derived_quality = STALE
                derived_reason = derived_reason or "STALE_RECEIVE_AGE"
            else:
                derived_quality = EXPLOITABLE
        return cls(
            venue=str(venue).strip().lower(),
            coin=canonical_coin(coin),
            exchange_symbol=str(exchange_symbol).strip().upper(),
            bid=float(bid_f or 0.0),
            ask=float(ask_f or 0.0),
            exchange_ts_ms=int(exchange_ts_ms),
            receive_ts_ms=int(receive_ts_ms),
            quality=str(derived_quality),
            bids=tuple(bids),
            asks=tuple(asks),
            last=_finite_positive(last),
            mark=_finite_positive(mark),
            index=_finite_positive(index),
            volume_24h=_finite_positive(volume_24h),
            open_interest=_finite_positive(open_interest),
            funding_rate=_float_or_none(funding_rate),
            funding_interval_hours=_finite_positive(funding_interval_hours),
            sequence=int(sequence) if sequence is not None else None,
            reason=derived_reason,
            real_execution=False,
        )

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0 if self.bid > 0.0 and self.ask >= self.bid else 0.0

    @property
    def spread_bps(self) -> float:
        mid = self.mid
        return ((self.ask - self.bid) / mid * 10_000.0) if mid > 0.0 else 0.0

    @property
    def exploitable(self) -> bool:
        return self.quality == EXPLOITABLE and self.mid > 0.0

    def freshness_ms(self, now_ms: int | None = None) -> int:
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        return max(0, now - self.receive_ts_ms)

    def with_freshness(self, *, now_ms: int, stale_after_ms: int) -> "NativeMarketSnapshot":
        if self.quality in {DESYNC, UNMEASURABLE}:
            return self
        if self.freshness_ms(now_ms) > stale_after_ms:
            return replace(self, quality=STALE, reason="STALE_RECEIVE_AGE")
        if self.mid > 0.0:
            return replace(self, quality=EXPLOITABLE, reason="")
        return replace(self, quality=UNMEASURABLE, reason="INVALID_BBO")


def _float_or_none(value: float | int | str | None) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


class MultiVenueMarketStore:
    """Last-value store with fail-closed freshness gates for strategy consumers."""

    def __init__(self, *, stale_after_ms: int = 1_000) -> None:
        self.stale_after_ms = int(stale_after_ms)
        self._snapshots: dict[tuple[str, str], NativeMarketSnapshot] = {}

    def put(self, snapshot: NativeMarketSnapshot) -> None:
        self._snapshots[(snapshot.venue, snapshot.coin)] = snapshot

    def get(self, venue: str, coin: str, *, now_ms: int) -> NativeMarketSnapshot | None:
        snap = self._snapshots.get((venue.lower(), canonical_coin(coin)))
        return None if snap is None else snap.with_freshness(now_ms=now_ms, stale_after_ms=self.stale_after_ms)

    def healthy(self, coin: str, *, now_ms: int) -> list[NativeMarketSnapshot]:
        target = canonical_coin(coin)
        rows = [
            snap.with_freshness(now_ms=now_ms, stale_after_ms=self.stale_after_ms)
            for (_venue, item_coin), snap in self._snapshots.items()
            if item_coin == target
        ]
        return sorted((row for row in rows if row.exploitable), key=lambda row: row.venue)

    def candidate_coins(self, *, now_ms: int, min_venues: int = 2) -> list[str]:
        coins = sorted({coin for _venue, coin in self._snapshots})
        return [coin for coin in coins if len(self.healthy(coin, now_ms=now_ms)) >= int(min_venues)]

    def cross_source_prices(self, coin: str, *, now_ms: int) -> list[CrossSourcePrice]:
        return [
            CrossSourcePrice(source=snap.venue, coin=snap.coin, bid=snap.bid, ask=snap.ask)
            for snap in self.healthy(coin, now_ms=now_ms)
        ]

    def venue_pairs(self, coin: str, *, now_ms: int) -> list[tuple[str, str]]:
        venues = [snap.venue for snap in self.healthy(coin, now_ms=now_ms)]
        return list(combinations(venues, 2))

    def lead_lag_rows(self, coin: str, *, now_ms: int) -> list[dict[str, float | int | str]]:
        return [
            {
                "venue": snap.venue,
                "coin": snap.coin,
                "mid": snap.mid,
                "bid": snap.bid,
                "ask": snap.ask,
                "exchange_ts_ms": snap.exchange_ts_ms,
                "receive_ts_ms": snap.receive_ts_ms,
            }
            for snap in self.healthy(coin, now_ms=now_ms)
        ]


__all__ = [
    "DESYNC",
    "EXPLOITABLE",
    "MarketLevel",
    "MultiVenueMarketStore",
    "NativeMarketSnapshot",
    "SCHEMA_VERSION",
    "STALE",
    "UNMEASURABLE",
    "canonical_coin",
]
