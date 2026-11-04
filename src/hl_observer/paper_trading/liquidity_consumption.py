"""Thread-safe paper liquidity consumption for one observed book state.

The ledger prevents several simulated strategies from reusing the same visible
units of liquidity. Consumption is keyed by venue, snapshot, coin, execution
side and price level. Retrying the same execution plan is idempotent.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from threading import RLock
from typing import Any, Generic, TypeVar

from hl_observer.instrument_identity import preserve_native_instrument_symbol
from hl_observer.paper_trading.execution_truth import (
    ExecutionTruth,
    normalize_execution_side,
)

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class LevelConsumption:
    venue: str
    snapshot_id: str
    coin: str
    execution_side: str
    price: float
    consumed_quantity: float


@dataclass(frozen=True, slots=True)
class LiquidityReservation:
    plan_id: str
    venue: str
    snapshot_id: str
    coin: str
    execution_side: str
    levels: tuple[LevelConsumption, ...]
    replayed: bool = False

    @property
    def consumed_quantity(self) -> float:
        return round(sum(level.consumed_quantity for level in self.levels), 12)


@dataclass(frozen=True, slots=True)
class ConsumptionOutcome(Generic[T]):
    result: T
    reservation: LiquidityReservation


class LiquidityConsumptionLedger:
    """Serialize paper fills against residual visible L2 depth."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._consumed: dict[tuple[str, str, str, str, float], float] = {}
        self._outcomes: dict[str, ConsumptionOutcome[object]] = {}

    def execute_once(
        self,
        *,
        plan_id: str,
        truth: ExecutionTruth,
        execution_side: str,
        execute: Callable[[ExecutionTruth | None], T],
    ) -> ConsumptionOutcome[T]:
        """Execute atomically on residual depth and reserve actual level fills."""

        normalized_side = normalize_execution_side(execution_side)
        normalized_plan = str(plan_id or "").strip()
        if not normalized_plan:
            raise ValueError("plan_id is required")
        with self._lock:
            previous = self._outcomes.get(normalized_plan)
            if previous is not None:
                reservation = LiquidityReservation(
                    plan_id=previous.reservation.plan_id,
                    venue=previous.reservation.venue,
                    snapshot_id=previous.reservation.snapshot_id,
                    coin=previous.reservation.coin,
                    execution_side=previous.reservation.execution_side,
                    levels=previous.reservation.levels,
                    replayed=True,
                )
                return ConsumptionOutcome(
                    result=previous.result,  # type: ignore[arg-type]
                    reservation=reservation,
                )

            residual = self._residual_truth(truth, normalized_side)
            result = execute(residual)
            consumptions = self._consume_result(
                truth=truth,
                execution_side=normalized_side,
                result=result,
            )
            reservation = LiquidityReservation(
                plan_id=normalized_plan,
                venue=truth.source,
                snapshot_id=truth.snapshot_id,
                coin=truth.coin,
                execution_side=normalized_side,
                levels=consumptions,
            )
            outcome: ConsumptionOutcome[T] = ConsumptionOutcome(
                result=result,
                reservation=reservation,
            )
            self._outcomes[normalized_plan] = outcome
            return outcome

    def consumed_quantity(
        self,
        *,
        venue: str,
        snapshot_id: str,
        coin: str,
        execution_side: str,
        price: float,
    ) -> float:
        key = self._key(
            venue=venue,
            snapshot_id=snapshot_id,
            coin=coin,
            execution_side=execution_side,
            price=price,
        )
        with self._lock:
            return round(self._consumed.get(key, 0.0), 12)

    def snapshot(self) -> tuple[LevelConsumption, ...]:
        with self._lock:
            rows = [
                LevelConsumption(
                    venue=venue,
                    snapshot_id=snapshot_id,
                    coin=coin,
                    execution_side=side,
                    price=price,
                    consumed_quantity=round(quantity, 12),
                )
                for (venue, snapshot_id, coin, side, price), quantity in self._consumed.items()
            ]
        return tuple(
            sorted(
                rows,
                key=lambda row: (
                    row.venue,
                    row.snapshot_id,
                    row.coin,
                    row.execution_side,
                    row.price,
                ),
            )
        )

    def _residual_truth(
        self,
        truth: ExecutionTruth,
        execution_side: str,
    ) -> ExecutionTruth | None:
        target = truth.levels_for_side(execution_side)
        residual_target: list[tuple[float, float]] = []
        for price, size in target:
            consumed = self._consumed.get(
                self._key(
                    venue=truth.source,
                    snapshot_id=truth.snapshot_id,
                    coin=truth.coin,
                    execution_side=execution_side,
                    price=price,
                ),
                0.0,
            )
            residual = max(0.0, float(size) - consumed)
            if residual > 1e-12:
                residual_target.append((price, residual))
        if not residual_target:
            return None
        bids = residual_target if execution_side == "SELL" else truth.bids
        asks = residual_target if execution_side == "BUY" else truth.asks
        return ExecutionTruth.from_levels(
            coin=truth.coin,
            bids=bids,
            asks=asks,
            received_ts_ms=truth.received_ts_ms,
            exchange_ts_ms=truth.exchange_ts_raw,
            source=truth.source,
            snapshot_id=truth.snapshot_id,
            data_origin=truth.data_origin,
        )

    def _consume_result(
        self,
        *,
        truth: ExecutionTruth,
        execution_side: str,
        result: object,
    ) -> tuple[LevelConsumption, ...]:
        raw_fills = tuple(getattr(result, "level_fills", ()) or ())
        rows: list[LevelConsumption] = []
        for fill in raw_fills:
            price = float(fill.price)
            quantity = max(0.0, float(fill.filled_quantity))
            if quantity <= 0:
                continue
            key = self._key(
                venue=truth.source,
                snapshot_id=truth.snapshot_id,
                coin=truth.coin,
                execution_side=execution_side,
                price=price,
            )
            visible = _visible_quantity(truth, execution_side, price)
            already = self._consumed.get(key, 0.0)
            if already + quantity > visible + 1e-9:
                raise RuntimeError("paper liquidity over-consumption detected")
            self._consumed[key] = already + quantity
            rows.append(
                LevelConsumption(
                    venue=truth.source,
                    snapshot_id=truth.snapshot_id,
                    coin=truth.coin,
                    execution_side=execution_side,
                    price=price,
                    consumed_quantity=round(quantity, 12),
                )
            )
        return tuple(rows)

    @staticmethod
    def _key(
        *,
        venue: str,
        snapshot_id: str,
        coin: str,
        execution_side: str,
        price: float,
    ) -> tuple[str, str, str, str, float]:
        return (
            str(venue).strip().lower(),
            str(snapshot_id),
            preserve_native_instrument_symbol(coin),
            normalize_execution_side(execution_side),
            round(float(price), 12),
        )


def _visible_quantity(
    truth: ExecutionTruth,
    execution_side: str,
    price: float,
) -> float:
    target = round(float(price), 12)
    return sum(
        size
        for level_price, size in truth.levels_for_side(execution_side)
        if round(float(level_price), 12) == target
    )


def _liquidity_base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _liquidity_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _liquidity_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def liquidity_consumption_safety_receipt(ledger: LiquidityConsumptionLedger) -> dict[str, Any]:
    valid = isinstance(ledger, LiquidityConsumptionLedger) and ledger.snapshot() == tuple(sorted(ledger.snapshot(), key=lambda row: (row.venue, row.snapshot_id, row.coin, row.execution_side, row.price)))
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_CONSUMPTION_SAFE" if valid else "LIQUIDITY_CONSUMPTION_UNSAFE", fail_closed=not valid)


def liquidity_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_FIELD_PRESENT" if valid else "LIQUIDITY_FIELD_MISSING", field=field, fail_closed=not valid)


def liquidity_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_FIELD_NON_NULL" if valid else "LIQUIDITY_FIELD_NULL", field=field, fail_closed=not valid)


def liquidity_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_FIELD_TYPE_VALID" if valid else "LIQUIDITY_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def liquidity_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _liquidity_finite(value)
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_VALUE_FINITE" if valid else "LIQUIDITY_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def liquidity_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _liquidity_integer(event_ts_ms) and _liquidity_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_EVENT_WITHIN_CUTOFF" if valid else "LIQUIDITY_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def liquidity_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _liquidity_integer(event_ts_ms) and _liquidity_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_EVENT_AGE_VALID" if valid else "LIQUIDITY_EVENT_TOO_OLD", fail_closed=not valid)


def liquidity_duplicate_receipt(*, event_ids: list[Any]) -> dict[str, Any]:
    valid = bool(event_ids) and all(str(value).strip() for value in event_ids) and len(event_ids) == len(set(event_ids))
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_EVENTS_UNIQUE" if valid else "LIQUIDITY_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def liquidity_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _liquidity_integer(attempts) and _liquidity_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_RETRY_BOUNDED" if valid else "LIQUIDITY_RETRY_UNSAFE", fail_closed=not valid)


def liquidity_replay_receipt(*, outputs: list[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_REPLAY_DETERMINISTIC" if valid else "LIQUIDITY_REPLAY_DIVERGED", fail_closed=not valid)


def liquidity_depth_receipt(*, bids: Sequence[Sequence[Any]], asks: Sequence[Sequence[Any]], is_bbo: bool) -> dict[str, Any]:
    valid = bool(bids) and bool(asks) and is_bbo is False and all(len(level) >= 2 and _liquidity_finite(level[0]) and _liquidity_finite(level[1]) and float(level[1]) > 0 for level in (*bids, *asks))
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_FULL_DEPTH" if valid else "LIQUIDITY_BBO_OR_INVALID_DEPTH", fail_closed=not valid)


def liquidity_crossed_book_receipt(*, best_bid: Any, best_ask: Any) -> dict[str, Any]:
    valid = _liquidity_finite(best_bid) and _liquidity_finite(best_ask) and float(best_ask) >= float(best_bid) > 0
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_BOOK_NOT_CROSSED" if valid else "LIQUIDITY_BOOK_CROSSED_OR_INVALID", fail_closed=not valid)


def liquidity_negative_size_receipt(*, sizes: Sequence[Any]) -> dict[str, Any]:
    valid = bool(sizes) and all(_liquidity_finite(size) and float(size) > 0 for size in sizes)
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_SIZES_POSITIVE" if valid else "LIQUIDITY_NEGATIVE_OR_ZERO_SIZE", fail_closed=not valid)


def liquidity_tick_receipt(*, prices: Sequence[Any], tick_size: Any) -> dict[str, Any]:
    try:
        tick = float(tick_size)
        valid = math.isfinite(tick) and tick > 0 and bool(prices) and all(abs((float(price) / tick) - round(float(price) / tick)) <= 1e-9 for price in prices)
    except (TypeError, ValueError, OverflowError):
        valid = False
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_TICK_ALIGNED" if valid else "LIQUIDITY_TICK_INVALID", fail_closed=not valid)


def liquidity_delta_receipt(*, has_snapshot: bool, delta_count: Any) -> dict[str, Any]:
    valid = has_snapshot is True and _liquidity_integer(delta_count) and delta_count > 0
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_DELTA_HAS_SNAPSHOT" if valid else "LIQUIDITY_DELTA_WITHOUT_SNAPSHOT", fail_closed=not valid)


def liquidity_staleness_receipt(*, now_ms: Any, received_ts_ms: Any, max_age_ms: Any) -> dict[str, Any]:
    valid = all(_liquidity_integer(value) for value in (now_ms, received_ts_ms, max_age_ms)) and now_ms >= received_ts_ms and now_ms - received_ts_ms <= max_age_ms
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_FRESH" if valid else "LIQUIDITY_STALE", fail_closed=not valid)


def liquidity_quantity_receipt(*, requested_quantity: Any, visible_depth: Any) -> dict[str, Any]:
    valid = _liquidity_finite(requested_quantity) and _liquidity_finite(visible_depth) and 0 < float(requested_quantity) <= float(visible_depth)
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_QUANTITY_WITHIN_DEPTH" if valid else "LIQUIDITY_QUANTITY_EXCEEDS_DEPTH", fail_closed=not valid)


def liquidity_consumption_receipt(*, consumed_quantity: Any, available_quantity: Any, already_consumed: Any) -> dict[str, Any]:
    valid = all(_liquidity_finite(value) for value in (consumed_quantity, available_quantity, already_consumed)) and min(float(consumed_quantity), float(available_quantity), float(already_consumed)) >= 0 and float(consumed_quantity) + float(already_consumed) <= float(available_quantity)
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_CONSUMPTION_ONCE" if valid else "LIQUIDITY_DOUBLE_CONSUMPTION", fail_closed=not valid)


def liquidity_maker_touch_receipt(*, touched: bool, executed: bool) -> dict[str, Any]:
    valid = touched is False or executed is True
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_MAKER_EXECUTION_CONFIRMED" if valid else "LIQUIDITY_TOUCH_ONLY_NOT_FILL", fail_closed=not valid)


def liquidity_fee_order_receipt(*, maker_fee_bps: Any, taker_fee_bps: Any) -> dict[str, Any]:
    valid = _liquidity_finite(maker_fee_bps) and _liquidity_finite(taker_fee_bps) and float(maker_fee_bps) >= 0 and float(taker_fee_bps) >= float(maker_fee_bps)
    return _liquidity_base("PROVEN" if valid else "REJECTED", verdict="LIQUIDITY_FEE_ORDER_VALID" if valid else "LIQUIDITY_FEE_ORDER_INVERTED", fail_closed=not valid)


__all__ = [
    "ConsumptionOutcome",
    "LevelConsumption",
    "LiquidityConsumptionLedger",
    "LiquidityReservation",
    "liquidity_consumption_safety_receipt",
    "liquidity_required_field_receipt",
    "liquidity_null_field_receipt",
    "liquidity_field_type_receipt",
    "liquidity_finite_receipt",
    "liquidity_cutoff_receipt",
    "liquidity_age_receipt",
    "liquidity_duplicate_receipt",
    "liquidity_retry_receipt",
    "liquidity_replay_receipt",
    "liquidity_depth_receipt",
    "liquidity_crossed_book_receipt",
    "liquidity_negative_size_receipt",
    "liquidity_tick_receipt",
    "liquidity_delta_receipt",
    "liquidity_staleness_receipt",
    "liquidity_quantity_receipt",
    "liquidity_consumption_receipt",
    "liquidity_maker_touch_receipt",
    "liquidity_fee_order_receipt",
]
