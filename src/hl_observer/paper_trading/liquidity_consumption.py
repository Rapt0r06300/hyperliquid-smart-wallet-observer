"""Thread-safe paper liquidity consumption for one observed book state.

The ledger prevents several simulated strategies from reusing the same visible
units of liquidity. Consumption is keyed by venue, snapshot, coin, execution
side and price level. Retrying the same execution plan is idempotent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import RLock
from typing import Generic, TypeVar

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
            exchange_ts_ms=truth.exchange_ts_ms,
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
            price = float(getattr(fill, "price"))
            quantity = max(0.0, float(getattr(fill, "filled_quantity")))
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
            str(coin).upper(),
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


__all__ = [
    "ConsumptionOutcome",
    "LevelConsumption",
    "LiquidityConsumptionLedger",
    "LiquidityReservation",
]
