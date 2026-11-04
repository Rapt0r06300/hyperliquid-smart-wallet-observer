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
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

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


def _truth_base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _truth_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _truth_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def execution_truth_safety_receipt(truth: ExecutionTruth) -> dict[str, Any]:
    valid = (
        isinstance(truth, ExecutionTruth)
        and truth.data_origin in {"REAL", "RECORDED_REAL"}
        and bool(truth.coin)
        and bool(truth.snapshot_id)
        and bool(truth.source)
        and bool(truth.bids)
        and bool(truth.asks)
        and truth.best_ask >= truth.best_bid
    )
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_SAFE" if valid else "EXECUTION_TRUTH_UNSAFE", fail_closed=not valid)


def truth_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_FIELD_PRESENT" if valid else "EXECUTION_TRUTH_FIELD_MISSING", field=field, fail_closed=not valid)


def truth_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_FIELD_NON_NULL" if valid else "EXECUTION_TRUTH_FIELD_NULL", field=field, fail_closed=not valid)


def truth_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_FIELD_TYPE_VALID" if valid else "EXECUTION_TRUTH_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def truth_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _truth_finite(value)
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_VALUE_FINITE" if valid else "EXECUTION_TRUTH_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def truth_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _truth_integer(event_ts_ms) and _truth_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_EVENT_WITHIN_CUTOFF" if valid else "EXECUTION_TRUTH_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def truth_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _truth_integer(event_ts_ms) and _truth_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_EVENT_AGE_VALID" if valid else "EXECUTION_TRUTH_EVENT_TOO_OLD", fail_closed=not valid)


def truth_duplicate_receipt(*, event_ids: list[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_EVENTS_UNIQUE" if valid else "EXECUTION_TRUTH_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def truth_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _truth_integer(attempts) and _truth_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_RETRY_BOUNDED" if valid else "EXECUTION_TRUTH_RETRY_UNSAFE", fail_closed=not valid)


def truth_replay_receipt(*, outputs: list[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_REPLAY_DETERMINISTIC" if valid else "EXECUTION_TRUTH_REPLAY_DIVERGED", fail_closed=not valid)


def truth_depth_receipt(*, bids: Sequence[Sequence[Any]], asks: Sequence[Sequence[Any]], is_bbo: bool) -> dict[str, Any]:
    valid = bool(bids) and bool(asks) and is_bbo is False and all(len(level) >= 2 and _truth_finite(level[0]) and _truth_finite(level[1]) and float(level[1]) > 0 for level in (*bids, *asks))
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_FULL_DEPTH" if valid else "EXECUTION_TRUTH_BBO_OR_INVALID_DEPTH", fail_closed=not valid)


def truth_crossed_book_receipt(*, best_bid: Any, best_ask: Any) -> dict[str, Any]:
    valid = _truth_finite(best_bid) and _truth_finite(best_ask) and float(best_ask) >= float(best_bid) > 0
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_BOOK_NOT_CROSSED" if valid else "EXECUTION_TRUTH_BOOK_CROSSED_OR_INVALID", fail_closed=not valid)


def truth_negative_size_receipt(*, sizes: Sequence[Any]) -> dict[str, Any]:
    valid = bool(sizes) and all(_truth_finite(size) and float(size) > 0 for size in sizes)
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_SIZES_POSITIVE" if valid else "EXECUTION_TRUTH_NEGATIVE_OR_ZERO_SIZE", fail_closed=not valid)


def truth_tick_receipt(*, prices: Sequence[Any], tick_size: Any) -> dict[str, Any]:
    try:
        tick = Decimal(str(tick_size))
        valid = tick > 0 and bool(prices) and all(Decimal(str(price)) % tick == 0 for price in prices)
    except (InvalidOperation, TypeError, ValueError, OverflowError):
        valid = False
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_TICK_ALIGNED" if valid else "EXECUTION_TRUTH_TICK_INVALID", fail_closed=not valid)


def truth_delta_receipt(*, has_snapshot: bool, delta_count: Any) -> dict[str, Any]:
    valid = has_snapshot is True and _truth_integer(delta_count) and delta_count > 0
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_DELTA_HAS_SNAPSHOT" if valid else "EXECUTION_TRUTH_DELTA_WITHOUT_SNAPSHOT", fail_closed=not valid)


def truth_staleness_receipt(*, now_ms: Any, received_ts_ms: Any, max_age_ms: Any) -> dict[str, Any]:
    valid = all(_truth_integer(value) for value in (now_ms, received_ts_ms, max_age_ms)) and now_ms >= received_ts_ms and now_ms - received_ts_ms <= max_age_ms
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_FRESH" if valid else "EXECUTION_TRUTH_STALE", fail_closed=not valid)


def truth_quantity_receipt(*, requested_quantity: Any, visible_depth: Any) -> dict[str, Any]:
    valid = _truth_finite(requested_quantity) and _truth_finite(visible_depth) and 0 < float(requested_quantity) <= float(visible_depth)
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_QUANTITY_WITHIN_DEPTH" if valid else "EXECUTION_TRUTH_QUANTITY_EXCEEDS_DEPTH", fail_closed=not valid)


def truth_consumption_receipt(*, consumed_quantity: Any, available_quantity: Any, already_consumed: Any) -> dict[str, Any]:
    valid = all(_truth_finite(value) for value in (consumed_quantity, available_quantity, already_consumed)) and min(float(consumed_quantity), float(available_quantity), float(already_consumed)) >= 0 and float(consumed_quantity) + float(already_consumed) <= float(available_quantity)
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_CONSUMPTION_ONCE" if valid else "EXECUTION_TRUTH_DOUBLE_CONSUMPTION", fail_closed=not valid)


def truth_maker_touch_receipt(*, touched: bool, executed: bool) -> dict[str, Any]:
    valid = touched is False or executed is True
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_MAKER_EXECUTION_CONFIRMED" if valid else "EXECUTION_TRUTH_TOUCH_ONLY_NOT_FILL", fail_closed=not valid)


def truth_fee_order_receipt(*, maker_fee_bps: Any, taker_fee_bps: Any) -> dict[str, Any]:
    valid = _truth_finite(maker_fee_bps) and _truth_finite(taker_fee_bps) and float(maker_fee_bps) >= 0 and float(taker_fee_bps) >= float(maker_fee_bps)
    return _truth_base("PROVEN" if valid else "REJECTED", verdict="EXECUTION_TRUTH_FEE_ORDER_VALID" if valid else "EXECUTION_TRUTH_FEE_ORDER_INVERTED", fail_closed=not valid)


__all__ = [
    "ExecutionTruth",
    "Levels",
    "MAX_SUPPORTED_EPOCH_MS",
    "normalize_execution_side",
    "execution_truth_safety_receipt",
    "truth_required_field_receipt",
    "truth_null_field_receipt",
    "truth_field_type_receipt",
    "truth_finite_receipt",
    "truth_cutoff_receipt",
    "truth_age_receipt",
    "truth_duplicate_receipt",
    "truth_retry_receipt",
    "truth_replay_receipt",
    "truth_depth_receipt",
    "truth_crossed_book_receipt",
    "truth_negative_size_receipt",
    "truth_tick_receipt",
    "truth_delta_receipt",
    "truth_staleness_receipt",
    "truth_quantity_receipt",
    "truth_consumption_receipt",
    "truth_maker_touch_receipt",
    "truth_fee_order_receipt",
]
