"""Causal execution truth used by strict local paper accounting.

An :class:`ExecutionTruth` is intentionally small: it binds one observed L2
snapshot, its timestamps and provenance to the exact bid/ask levels that were
available when a paper decision was made.  Strict PnL paths must not replace a
missing truth with a configured depth or a generic spread estimate.

This module is pure and local-only.  It does not fetch data and exposes no
venue execution surface.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from hashlib import sha256

Levels = tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class ExecutionTruth:
    coin: str
    snapshot_id: str
    source: str
    exchange_ts_ms: int | None
    received_ts_ms: int
    bids: Levels
    asks: Levels
    data_origin: str = "REAL"

    @classmethod
    def from_levels(
        cls,
        *,
        coin: str,
        bids: Iterable[tuple[float, float]],
        asks: Iterable[tuple[float, float]],
        received_ts_ms: int,
        exchange_ts_ms: int | None = None,
        source: str,
        snapshot_id: str | None = None,
        data_origin: str = "REAL",
    ) -> ExecutionTruth:
        clean_bids = _clean_levels(bids, reverse=True)
        clean_asks = _clean_levels(asks, reverse=False)
        normalized_coin = str(coin or "").strip().upper()
        normalized_origin = str(data_origin or "").strip().upper()
        normalized_source = str(source or "").strip()
        if not normalized_coin:
            raise ValueError("execution truth coin is required")
        if normalized_origin not in {"REAL", "RECORDED_REAL"}:
            raise ValueError("strict execution truth requires real observed data")
        if not normalized_source:
            raise ValueError("execution truth source is required")
        if not clean_bids or not clean_asks:
            raise ValueError("execution truth requires both bid and ask levels")
        if clean_bids[0][0] > clean_asks[0][0]:
            raise ValueError("crossed execution book")
        recv = _positive_int(received_ts_ms, "received_ts_ms")
        exch = None if exchange_ts_ms is None else _positive_int(exchange_ts_ms, "exchange_ts_ms")
        identity = snapshot_id or _snapshot_id(
            normalized_coin,
            normalized_source,
            exch,
            recv,
            clean_bids,
            clean_asks,
        )
        return cls(
            coin=normalized_coin,
            snapshot_id=str(identity),
            source=normalized_source,
            exchange_ts_ms=exch,
            received_ts_ms=recv,
            bids=clean_bids,
            asks=clean_asks,
            data_origin=normalized_origin,
        )

    @property
    def best_bid(self) -> float:
        return self.bids[0][0]

    @property
    def best_ask(self) -> float:
        return self.asks[0][0]

    @property
    def mid_price(self) -> float:
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread_bps(self) -> float:
        return (self.best_ask - self.best_bid) / self.mid_price * 10_000.0

    def age_ms(self, decision_ts_ms: int) -> int:
        decision = _positive_int(decision_ts_ms, "decision_ts_ms")
        return max(0, decision - self.received_ts_ms)

    def is_fresh(self, *, decision_ts_ms: int, max_age_ms: int) -> bool:
        return self.age_ms(decision_ts_ms) <= max(0, int(max_age_ms))

    def levels_for_side(self, side: str) -> Levels:
        normalized = normalize_execution_side(side)
        return self.asks if normalized == "BUY" else self.bids

    def visible_notional(self, side: str) -> float:
        return sum(price * size for price, size in self.levels_for_side(side))


def normalize_execution_side(side: str) -> str:
    normalized = str(side or "").strip().upper()
    if normalized in {"BUY", "LONG", "OPEN_LONG", "CLOSE_SHORT"}:
        return "BUY"
    if normalized in {"SELL", "SHORT", "OPEN_SHORT", "CLOSE_LONG"}:
        return "SELL"
    raise ValueError(f"invalid execution side: {side!r}")


def _clean_levels(levels: Iterable[tuple[float, float]], *, reverse: bool) -> Levels:
    clean: list[tuple[float, float]] = []
    for raw_price, raw_size in levels:
        price = _finite_positive(raw_price, "book price")
        size = _finite_positive(raw_size, "book size")
        clean.append((price, size))
    clean.sort(key=lambda row: row[0], reverse=reverse)
    return tuple(clean)


def _finite_positive(value: object, name: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return parsed


def _positive_int(value: object, name: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise ValueError(f"{name} must be positive")
    return parsed


def _snapshot_id(
    coin: str,
    source: str,
    exchange_ts_ms: int | None,
    received_ts_ms: int,
    bids: Levels,
    asks: Levels,
) -> str:
    material = repr((coin, source, exchange_ts_ms, received_ts_ms, bids, asks))
    return "book:" + sha256(material.encode("utf-8")).hexdigest()


__all__ = ["ExecutionTruth", "Levels", "normalize_execution_side"]
