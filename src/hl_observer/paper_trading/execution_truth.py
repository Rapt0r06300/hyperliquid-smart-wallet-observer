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

from hl_observer.instrument_identity import preserve_native_instrument_symbol

Levels = tuple[tuple[float, float], ...]
# Python datetime's last representable UTC millisecond. Values beyond this
# bound are not plausible epoch milliseconds and commonly indicate ns/ms mixups.
MAX_SUPPORTED_EPOCH_MS = 253_402_300_799_999


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
    exchange_ts_raw: object = None
    exchange_ts_status: str = "MISSING"
    received_ts_raw: object = None
    received_ts_unit: str = "ms_since_unix_epoch"

    @classmethod
    def from_levels(
        cls,
        *,
        coin: str,
        bids: Iterable[tuple[float, float]],
        asks: Iterable[tuple[float, float]],
        received_ts_ms: int,
        exchange_ts_ms: object = None,
        source: str,
        snapshot_id: str | None = None,
        data_origin: str = "REAL",
        received_ts_raw: object = None,
        received_ts_unit: str = "ms_since_unix_epoch",
    ) -> ExecutionTruth:
        clean_bids = _clean_levels(bids, reverse=True)
        clean_asks = _clean_levels(asks, reverse=False)
        normalized_coin = preserve_native_instrument_symbol(coin)
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
        received_raw = recv if received_ts_raw is None else received_ts_raw
        if received_ts_unit not in {
            "ms_since_unix_epoch",
            "s_since_unix_epoch_utc",
        }:
            raise ValueError("execution truth received timestamp unit is invalid")
        exch, exchange_status = _parse_source_timestamp(exchange_ts_ms)
        identity = snapshot_id or _snapshot_id(
            normalized_coin,
            normalized_source,
            exch,
            exchange_ts_ms,
            exchange_status,
            recv,
            received_raw,
            received_ts_unit,
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
            exchange_ts_raw=exchange_ts_ms,
            exchange_ts_status=exchange_status,
            received_ts_raw=received_raw,
            received_ts_unit=received_ts_unit,
        )

    @property
    def best_bid(self) -> float:
        return self.bids[0][0]

    @property
    def best_ask(self) -> float:
        return self.asks[0][0]

    @property
    def mid_price(self) -> float:
        mid = self.best_bid / 2.0 + self.best_ask / 2.0
        if not math.isfinite(mid) or mid <= 0.0:
            raise ValueError("NUMERIC_OVERFLOW_EXECUTION_MID")
        return mid

    @property
    def spread_bps(self) -> float:
        spread = (self.best_ask - self.best_bid) / self.mid_price * 10_000.0
        if not math.isfinite(spread) or spread < 0.0:
            raise ValueError("NUMERIC_OVERFLOW_EXECUTION_SPREAD")
        return spread

    def age_ms(self, decision_ts_ms: int) -> int:
        decision = _positive_int(decision_ts_ms, "decision_ts_ms")
        age = decision - self.received_ts_ms
        if age < 0:
            raise ValueError("execution truth received after decision")
        return age

    def is_fresh(self, *, decision_ts_ms: int, max_age_ms: int) -> bool:
        return self.timestamp_refusal_reason(
            decision_ts_ms=decision_ts_ms,
            max_age_ms=max_age_ms,
        ) is None

    def timestamp_refusal_reason(
        self,
        *,
        decision_ts_ms: int,
        max_age_ms: int | None = None,
    ) -> str | None:
        """Return a stable fail-closed reason for invalid/noncausal timestamps.

        Exchange, local receipt, and decision timestamps are separate evidence.
        No implicit clock-skew tolerance is applied: source time must not be
        later than receipt time, and both observations must precede the decision.
        """

        if type(decision_ts_ms) is not int or decision_ts_ms <= 0:
            return "DECISION_TIMESTAMP_INVALID"
        if self.exchange_ts_status == "MISSING":
            return "SOURCE_TIMESTAMP_MISSING"
        if self.exchange_ts_status != "VALID" or type(self.exchange_ts_ms) is not int:
            return "SOURCE_TIMESTAMP_INVALID"
        if self.exchange_ts_ms > decision_ts_ms:
            return "SOURCE_TIMESTAMP_AFTER_DECISION"
        if self.received_ts_ms > decision_ts_ms:
            return "RECEIVED_TIMESTAMP_AFTER_DECISION"
        if self.exchange_ts_ms > self.received_ts_ms:
            return "SOURCE_TIMESTAMP_AFTER_RECEIPT"
        if max_age_ms is not None:
            if type(max_age_ms) is not int or max_age_ms < 0:
                return "MAX_BOOK_AGE_INVALID"
            if decision_ts_ms - self.exchange_ts_ms > max_age_ms:
                return "STALE_SOURCE_TIMESTAMP"
            if decision_ts_ms - self.received_ts_ms > max_age_ms:
                return "STALE_RECEIVED_TIMESTAMP"
        return None

    def levels_for_side(self, side: str) -> Levels:
        normalized = normalize_execution_side(side)
        return self.asks if normalized == "BUY" else self.bids

    def visible_notional(self, side: str) -> float:
        total = 0.0
        for price, size in self.levels_for_side(side):
            level_notional = price * size
            if not math.isfinite(level_notional) or level_notional <= 0.0:
                raise ValueError("NUMERIC_OVERFLOW_VISIBLE_NOTIONAL")
            total += level_notional
            if not math.isfinite(total):
                raise ValueError("NUMERIC_OVERFLOW_VISIBLE_NOTIONAL")
        return total


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
    if type(value) is not int or not 0 < value <= MAX_SUPPORTED_EPOCH_MS:
        raise ValueError(f"{name} must be a supported positive epoch millisecond")
    return value


def _parse_source_timestamp(value: object) -> tuple[int | None, str]:
    if value is None:
        return None, "MISSING"
    if type(value) is not int or not 0 < value <= MAX_SUPPORTED_EPOCH_MS:
        return None, "INVALID"
    return value, "VALID"


def _snapshot_id(
    coin: str,
    source: str,
    exchange_ts_ms: int | None,
    exchange_ts_raw: object,
    exchange_ts_status: str,
    received_ts_ms: int,
    received_ts_raw: object,
    received_ts_unit: str,
    bids: Levels,
    asks: Levels,
) -> str:
    material = repr(
        (coin, source, exchange_ts_ms, type(exchange_ts_raw).__name__, exchange_ts_raw,
         exchange_ts_status, received_ts_ms, type(received_ts_raw).__name__,
         received_ts_raw, received_ts_unit, bids, asks)
    )
    return "book:" + sha256(material.encode("utf-8")).hexdigest()


__all__ = [
    "ExecutionTruth",
    "Levels",
    "MAX_SUPPORTED_EPOCH_MS",
    "normalize_execution_side",
]
