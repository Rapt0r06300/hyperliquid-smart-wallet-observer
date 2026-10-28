from __future__ import annotations

import math
import uuid
from copy import copy
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal, localcontext
from enum import Enum
from hashlib import sha256

from hl_observer.economics.numeric import (
    USD_RECONCILIATION_ABS_TOLERANCE,
    decimal_difference,
    decimal_sum,
    decimal_value,
    float_not_above,
    float_not_below,
)
from hl_observer.instrument_identity import preserve_native_instrument_symbol
from hl_observer.simulation.accounting_truth import first_not_none, named_roi_metrics
from hl_observer.simulation.capital_accounting import (
    CapitalAccountingSnapshot,
    CapitalAccountingTracker,
    PositionCapitalInput,
)
from hl_observer.simulation.fee_model import compute_fee_usdc
from hl_observer.simulation.ledger_integrity import GENESIS_HASH, seal_event, verify_chain
from hl_observer.simulation.paper_event import PaperEvent, PaperEventType
from hl_observer.simulation.pnl_ledger_audit import audit_paper_ledger
from hl_observer.simulation.pnl_reconciliation import PnlReconciliation, reconcile_pnl


@dataclass(slots=True)
class LedgerPosition:
    position_id: str
    coin: str
    side: str
    quantity: float
    average_entry_price: float
    opened_at_ms: int
    last_mark_price: float
    leverage_effective: float = 1.0
    leg_notional_usd: tuple[float, ...] = ()
    leg_direction: tuple[int, ...] = ()
    liquidation_buffer_bps: float | None = None
    last_liquidatable_price: float | None = None

    @property
    def notional_usdc(self) -> float:
        return abs(self.quantity) * self.average_entry_price

    def unrealized(self, mark_price: float | None = None) -> float:
        mark = float(mark_price if mark_price is not None else self.last_mark_price)
        if self.side == "LONG":
            return (mark - self.average_entry_price) * self.quantity
        return (self.average_entry_price - mark) * self.quantity

    def liquidatable_unrealized(self) -> float | None:
        if self.last_liquidatable_price is None:
            return None
        return self.unrealized(self.last_liquidatable_price)

    def capital_input(self) -> PositionCapitalInput:
        notionals = self.leg_notional_usd or (self.notional_usdc,)
        directions = self.leg_direction or (
            (1 if self.side == "LONG" else -1),
        )
        return PositionCapitalInput(
            position_id=self.position_id,
            leg_notional_usd=notionals,
            leg_direction=directions,
            leverage_effective=self.leverage_effective,
            unrealized_mid_pnl_usd=self.unrealized(),
            liquidatable_pnl_usd=self.liquidatable_unrealized(),
            liquidation_buffer_bps=self.liquidation_buffer_bps,
        )


@dataclass(slots=True)
class PaperLedger:
    starting_balance_usdc: float = 200.0
    session_id: str = field(default_factory=lambda: f"paper:{uuid.uuid4().hex}")
    events: list[PaperEvent] = field(default_factory=list)
    positions: dict[str, LedgerPosition] = field(default_factory=dict)
    realized_pnl_usdc: float = 0.0
    unrealized_pnl_usdc: float = 0.0
    fees_paid_usdc: float = 0.0
    funding_net_usdc: float = 0.0
    cash_balance_usdc: float | None = None
    high_water_equity_usdc: float | None = None
    drawdown_usdc: float = 0.0
    turnover_usdc: float = 0.0
    mark_evidence_complete: bool = True
    mark_evidence_gap_count: int = 0
    funding_evidence_complete: bool = True
    funding_settlement_ids: set[str] = field(default_factory=set, repr=False)
    last_missing_mark_position_ids: tuple[str, ...] = ()
    capital_tracker: CapitalAccountingTracker = field(init=False, repr=False)
    _cash_balance_exact: Decimal = field(init=False, repr=False)
    _fees_paid_exact: Decimal = field(init=False, repr=False)
    _realized_pnl_exact: Decimal = field(init=False, repr=False)
    _funding_net_exact: Decimal = field(init=False, repr=False)
    _turnover_exact: Decimal = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not _finite_positive(self.starting_balance_usdc):
            raise ValueError("starting_balance_usdc must be finite and positive")
        if self.cash_balance_usdc is not None and not math.isfinite(float(self.cash_balance_usdc)):
            raise ValueError("cash_balance_usdc must be finite")
        if self.high_water_equity_usdc is not None and not math.isfinite(float(self.high_water_equity_usdc)):
            raise ValueError("high_water_equity_usdc must be finite")
        if self.cash_balance_usdc is None:
            self.cash_balance_usdc = float(self.starting_balance_usdc)
        if self.high_water_equity_usdc is None:
            self.high_water_equity_usdc = float(self.starting_balance_usdc)
        exact_values = {
            "_cash_balance_exact": self.cash_balance_usdc,
            "_fees_paid_exact": self.fees_paid_usdc,
            "_realized_pnl_exact": self.realized_pnl_usdc,
            "_funding_net_exact": self.funding_net_usdc,
            "_turnover_exact": self.turnover_usdc,
        }
        for name, value in exact_values.items():
            exact = decimal_value(value)
            if exact is None:
                raise ValueError(f"{name.removeprefix('_')} must be finite")
            setattr(self, name, exact)
        self.capital_tracker = CapitalAccountingTracker(
            starting_equity_usd=self.starting_balance_usdc
        )
        self._observe_capital()

    @property
    def equity_usdc(self) -> float:
        exact_equity = decimal_sum(
            (self._cash_balance_exact, decimal_value(self.unrealized_pnl_usdc))
        )
        value = _finite_decimal_float(exact_equity)
        return math.inf if value is None else value

    def open_position(
        self,
        *,
        coin: str,
        side: str,
        notional_usdc: float,
        quantity: float | None = None,
        fill_price: float,
        timestamp_ms: int,
        fee_bps: float = 4.5,
        leverage_effective: float = 1.0,
        leg_notional_usd: tuple[float, ...] | None = None,
        leg_direction: tuple[int, ...] | None = None,
        liquidation_buffer_bps: float | None = None,
        position_id: str | None = None,
        refs: dict | None = None,
    ) -> PaperEvent:
        normalized_side = str(side).upper()
        if not _finite_nonnegative(fee_bps):
            return self.no_trade(coin=coin, reason="FEE_INVALID", timestamp_ms=timestamp_ms, refs=refs)
        if normalized_side not in {"LONG", "SHORT"}:
            return self.no_trade(coin=coin, reason="SIDE_INVALID", timestamp_ms=timestamp_ms, refs=refs)
        if (
            not _finite_positive(fill_price)
            or not _finite_positive(notional_usdc)
            or (quantity is not None and not _finite_positive(quantity))
        ):
            return self.no_trade(coin=coin, reason="FILL_INVALID", timestamp_ms=timestamp_ms, refs=refs)
        qty = (
            float(quantity)
            if quantity is not None
            else float(notional_usdc) / float(fill_price)
        )
        filled_notional = abs(qty * float(fill_price))
        if quantity is not None and not _notional_matches(
            quantity=quantity,
            fill_price=fill_price,
            notional_usdc=notional_usdc,
        ):
            return self.no_trade(
                coin=coin,
                reason="FILL_NOTIONAL_MISMATCH",
                timestamp_ms=timestamp_ms,
                refs={
                    **dict(refs or {}),
                    "requested_notional_usdc": float(notional_usdc),
                    "quantity_price_notional_usdc": filled_notional,
                },
            )
        if not _finite_positive(leverage_effective):
            return self.no_trade(
                coin=coin,
                reason="CAPITAL_LEVERAGE_INVALID",
                timestamp_ms=timestamp_ms,
                refs=refs,
            )
        leverage = max(1.0, float(leverage_effective))
        new_leg_notional = tuple(
            float(value)
            for value in (leg_notional_usd or (filled_notional,))
        )
        new_leg_direction = tuple(
            int(value)
            for value in (
                leg_direction
                or ((1 if normalized_side == "LONG" else -1),)
            )
        )
        if (
            len(new_leg_notional) != len(new_leg_direction)
            or not new_leg_notional
            or any(not _finite_positive(value) for value in new_leg_notional)
            or any(direction not in {-1, 1} for direction in new_leg_direction)
        ):
            return self.no_trade(
                coin=coin,
                reason="CAPITAL_LEG_SCHEMA_INVALID",
                timestamp_ms=timestamp_ms,
                refs=refs,
            )
        try:
            fee = compute_fee_usdc(filled_notional, fee_bps)
        except ValueError:
            return self.no_trade(
                coin=coin,
                reason="OPEN_ACCOUNTING_NON_FINITE",
                timestamp_ms=timestamp_ms,
                refs=refs,
            )
        exact_fee = decimal_value(fee)
        turnover_increment = decimal_sum(new_leg_notional)
        cash_after_exact = decimal_difference(self._cash_balance_exact, exact_fee)
        fees_after_exact = (
            decimal_sum((self._fees_paid_exact, exact_fee))
            if exact_fee is not None
            else None
        )
        turnover_after_exact = (
            decimal_sum((self._turnover_exact, turnover_increment))
            if turnover_increment is not None
            else None
        )
        cash_after_fee = _finite_decimal_float(cash_after_exact)
        fees_after = _finite_decimal_float(fees_after_exact)
        turnover_after = _finite_decimal_float(turnover_after_exact)
        if cash_after_fee is None or fees_after is None or turnover_after is None:
            return self.no_trade(
                coin=coin,
                reason="OPEN_ACCOUNTING_NON_FINITE",
                timestamp_ms=timestamp_ms,
                refs={"accounting_component": "EXACT_ACCUMULATOR"},
            )
        if not all(
            math.isfinite(value)
            for value in (fee, cash_after_fee, fees_after, turnover_after)
        ):
            return self.no_trade(
                coin=coin,
                reason="OPEN_ACCOUNTING_NON_FINITE",
                timestamp_ms=timestamp_ms,
                refs=refs,
            )
        key = self._position_key(
            coin,
            normalized_side,
            position_id=position_id,
        )
        existing = self.positions.get(key)
        if existing:
            existing_directions = existing.leg_direction or (
                (1 if existing.side == "LONG" else -1),
            )
            existing_notionals = existing.leg_notional_usd or (
                existing.notional_usdc,
            )
            if (
                len(existing_notionals) != len(new_leg_notional)
                or existing_directions != new_leg_direction
            ):
                return self.no_trade(
                    coin=coin,
                    reason="CAPITAL_LEG_SCHEMA_MISMATCH",
                    timestamp_ms=timestamp_ms,
                    refs=refs,
                )
            try:
                new_qty = math.fsum((existing.quantity, qty))
                weighted_entry = math.fsum(
                    (
                        existing.quantity * existing.average_entry_price,
                        qty * float(fill_price),
                    )
                )
                avg = weighted_entry / new_qty
                combined_legs = _combine_leg_notionals(
                    existing_notionals,
                    new_leg_notional,
                )
                existing_margin = math.fsum(existing_notionals) / max(
                    1.0,
                    existing.leverage_effective,
                )
                added_margin = math.fsum(new_leg_notional) / leverage
                combined_margin = math.fsum((existing_margin, added_margin))
                combined_gross = math.fsum(combined_legs)
                combined_leverage = combined_gross / combined_margin
            except (OverflowError, ValueError, ZeroDivisionError):
                return self.no_trade(
                    coin=coin,
                    reason="OPEN_ACCOUNTING_NON_FINITE",
                    timestamp_ms=timestamp_ms,
                    refs={"accounting_component": "POSITION_INCREASE"},
                )
            if not all(
                _finite_positive(value)
                for value in (
                    existing.quantity,
                    existing.average_entry_price,
                    existing.leverage_effective,
                    new_qty,
                    weighted_entry,
                    avg,
                    existing_margin,
                    added_margin,
                    combined_margin,
                    combined_gross,
                    combined_leverage,
                    *combined_legs,
                )
            ):
                return self.no_trade(
                    coin=coin,
                    reason="OPEN_ACCOUNTING_NON_FINITE",
                    timestamp_ms=timestamp_ms,
                    refs={"accounting_component": "POSITION_INCREASE"},
                )
            candidate_position = replace(
                existing,
                quantity=new_qty,
                average_entry_price=avg,
                last_mark_price=float(fill_price),
                leverage_effective=combined_leverage,
                leg_notional_usd=combined_legs,
                leg_direction=new_leg_direction,
                liquidation_buffer_bps=_minimum_optional(
                    existing.liquidation_buffer_bps,
                    liquidation_buffer_bps,
                ),
            )
            event_type = PaperEventType.POSITION_INCREASED
        else:
            candidate_position = LedgerPosition(
                position_id=key,
                coin=preserve_native_instrument_symbol(coin),
                side=normalized_side,
                quantity=qty,
                average_entry_price=float(fill_price),
                opened_at_ms=int(timestamp_ms),
                last_mark_price=float(fill_price),
                leverage_effective=leverage,
                leg_notional_usd=new_leg_notional,
                leg_direction=new_leg_direction,
                liquidation_buffer_bps=liquidation_buffer_bps,
            )
            event_type = PaperEventType.POSITION_OPENED
        candidate_positions = dict(self.positions)
        candidate_positions[key] = candidate_position
        candidate_tracker = copy(self.capital_tracker)
        try:
            candidate_tracker.observe(
                collateral_cash_usd=cash_after_fee,
                positions=tuple(
                    position.capital_input()
                    for position in candidate_positions.values()
                ),
                realized_pnl_usd=cash_after_fee - self.starting_balance_usdc,
                turnover_usd=turnover_after,
            )
            fee_event_probe = PaperEvent.create(
                PaperEventType.FEE_CHARGED,
                timestamp_ms=timestamp_ms,
                coin=preserve_native_instrument_symbol(coin),
                side=normalized_side,
                fee_usdc=fee,
                refs={"position_id": key, "accounting_component": "FEE"},
            )
            event_refs_probe = dict(refs or {})
            event_refs_probe.update(
                {
                    "position_id": key,
                    "fee_event_id": fee_event_probe.event_id,
                    "fee_accounting": "SEPARATE_EVENT",
                }
            )
            event_probe = PaperEvent.create(
                event_type,
                timestamp_ms=timestamp_ms,
                coin=preserve_native_instrument_symbol(coin),
                side=normalized_side,
                quantity=qty,
                price=float(fill_price),
                notional_usdc=filled_notional,
                fee_usdc=fee,
                refs=event_refs_probe,
            )
            previous_hash = self.events[-1].event_hash if self.events else GENESIS_HASH
            fee_row = seal_event(
                fee_event_probe.to_dict(),
                event_seq=len(self.events) + 1,
                session_id=self.session_id,
                prev_hash=str(previous_hash),
            )
            seal_event(
                event_probe.to_dict(),
                event_seq=len(self.events) + 2,
                session_id=self.session_id,
                prev_hash=str(fee_row["event_hash"]),
            )
        except (OverflowError, TypeError, ValueError):
            return self.no_trade(
                coin=coin,
                reason="OPEN_EVENT_OR_CAPITAL_INVALID",
                timestamp_ms=timestamp_ms,
                refs={"accounting_component": "OPEN_PREVALIDATION"},
            )

        self.turnover_usdc = turnover_after
        self._turnover_exact = turnover_after_exact
        fee_event = self._charge_fee(
            fee,
            coin=coin,
            side=normalized_side,
            timestamp_ms=timestamp_ms,
            position_id=key,
        )
        if existing:
            existing.quantity = candidate_position.quantity
            existing.average_entry_price = candidate_position.average_entry_price
            existing.last_mark_price = candidate_position.last_mark_price
            existing.leverage_effective = candidate_position.leverage_effective
            existing.leg_notional_usd = candidate_position.leg_notional_usd
            existing.leg_direction = candidate_position.leg_direction
            existing.liquidation_buffer_bps = candidate_position.liquidation_buffer_bps
        else:
            self.positions[key] = candidate_position
        self.capital_tracker = candidate_tracker
        event_refs = dict(refs or {})
        event_refs.update(
            {
                "position_id": key,
                "fee_event_id": fee_event.event_id,
                "fee_accounting": "SEPARATE_EVENT",
            }
        )
        event = PaperEvent.create(
            event_type,
            timestamp_ms=timestamp_ms,
            coin=preserve_native_instrument_symbol(coin),
            side=normalized_side,
            quantity=qty,
            price=float(fill_price),
            notional_usdc=filled_notional,
            fee_usdc=fee,
            refs=event_refs,
        )
        return self._append(event)

    def reduce_or_close(
        self,
        *,
        coin: str,
        side: str,
        quantity: float,
        fill_price: float,
        timestamp_ms: int,
        fee_bps: float = 4.5,
        reason: str = "leader_exit",
        position_id: str | None = None,
        refs: dict | None = None,
    ) -> PaperEvent:
        normalized_side = str(side).upper()
        if not _finite_nonnegative(fee_bps):
            return self.no_trade(coin=coin, reason="FEE_INVALID", timestamp_ms=timestamp_ms, refs=refs)
        key = self._position_key(
            coin,
            normalized_side,
            position_id=position_id,
        )
        pos = self.positions.get(key)
        if pos is None:
            return self.no_trade(
                coin=coin,
                reason="NO_MATCHING_PAPER_POSITION_FOR_CLOSE",
                timestamp_ms=timestamp_ms,
                refs=refs,
            )
        if not _finite_positive(quantity) or not _finite_positive(fill_price):
            return self.no_trade(coin=coin, reason="EXIT_FILL_INVALID", timestamp_ms=timestamp_ms, refs=refs)
        if not _finite_positive(pos.quantity) or not _finite_positive(pos.average_entry_price):
            return self.no_trade(
                coin=coin,
                reason="POSITION_STATE_INVALID",
                timestamp_ms=timestamp_ms,
                refs=refs,
            )
        close_qty = min(float(quantity), pos.quantity)
        if close_qty <= 0:
            return self.no_trade(coin=coin, reason="EXIT_FILL_INVALID", timestamp_ms=timestamp_ms, refs=refs)
        if normalized_side == "LONG":
            gross = (float(fill_price) - pos.average_entry_price) * close_qty
        else:
            gross = (pos.average_entry_price - float(fill_price)) * close_qty
        notional = close_qty * float(fill_price)
        if not math.isfinite(gross) or not math.isfinite(notional):
            return self.no_trade(
                coin=coin,
                reason="EXIT_ACCOUNTING_NON_FINITE",
                timestamp_ms=timestamp_ms,
                refs=refs,
            )
        try:
            fee = compute_fee_usdc(notional, fee_bps)
        except ValueError:
            return self.no_trade(
                coin=coin,
                reason="EXIT_ACCOUNTING_NON_FINITE",
                timestamp_ms=timestamp_ms,
                refs=refs,
            )
        if not math.isfinite(fee):
            return self.no_trade(
                coin=coin,
                reason="EXIT_ACCOUNTING_NON_FINITE",
                timestamp_ms=timestamp_ms,
                refs=refs,
            )
        exact_gross = decimal_value(gross)
        exact_fee = decimal_value(fee)
        realized_after_exact = (
            decimal_sum((self._realized_pnl_exact, exact_gross))
            if exact_gross is not None
            else None
        )
        cash_before_fee_exact = (
            decimal_sum((self._cash_balance_exact, exact_gross))
            if exact_gross is not None
            else None
        )
        cash_after_fee_exact = decimal_difference(cash_before_fee_exact, exact_fee)
        fees_after_exact = (
            decimal_sum((self._fees_paid_exact, exact_fee))
            if exact_fee is not None
            else None
        )
        realized_after = _finite_decimal_float(realized_after_exact)
        cash_before_fee = _finite_decimal_float(cash_before_fee_exact)
        cash_after_fee = _finite_decimal_float(cash_after_fee_exact)
        fees_after = _finite_decimal_float(fees_after_exact)
        original_quantity = pos.quantity
        remaining_quantity = original_quantity - close_qty
        close_fraction = min(1.0, close_qty / max(original_quantity, 1e-12))
        current_legs = pos.leg_notional_usd or (notional,)
        closed_leg_notional = tuple(value * close_fraction for value in current_legs)
        remaining_legs = tuple(
            max(0.0, value - closed)
            for value, closed in zip(current_legs, closed_leg_notional, strict=True)
        )
        turnover_increment = decimal_sum(closed_leg_notional)
        turnover_after_exact = (
            decimal_sum((self._turnover_exact, turnover_increment))
            if turnover_increment is not None
            else None
        )
        turnover_after = _finite_decimal_float(turnover_after_exact)
        if any(
            value is None
            for value in (
                realized_after,
                cash_before_fee,
                cash_after_fee,
                fees_after,
                turnover_after,
                realized_after_exact,
                cash_before_fee_exact,
                cash_after_fee_exact,
                fees_after_exact,
                turnover_after_exact,
            )
        ) or not all(
            math.isfinite(value)
            for value in (
                realized_after,
                cash_before_fee,
                cash_after_fee,
                fees_after,
                remaining_quantity,
                close_fraction,
                turnover_after,
                *closed_leg_notional,
                *remaining_legs,
            )
        ):
            return self.no_trade(
                coin=coin,
                reason="EXIT_ACCOUNTING_NON_FINITE",
                timestamp_ms=timestamp_ms,
                refs=refs,
            )
        fully_closed = remaining_quantity <= 1e-12
        staged = copy(self)
        staged.events = list(self.events)
        staged.positions = {
            current_key: replace(current)
            for current_key, current in self.positions.items()
        }
        staged.capital_tracker = copy(self.capital_tracker)
        staged.realized_pnl_usdc = realized_after
        staged._realized_pnl_exact = realized_after_exact
        staged.cash_balance_usdc = cash_before_fee
        staged._cash_balance_exact = cash_before_fee_exact
        staged.turnover_usdc = turnover_after
        staged._turnover_exact = turnover_after_exact
        staged_position = staged.positions[key]
        staged_position.quantity = remaining_quantity
        staged_position.last_mark_price = float(fill_price)
        staged_position.leg_notional_usd = remaining_legs
        if fully_closed:
            del staged.positions[key]
        try:
            fee_event = staged._charge_fee(
                fee,
                coin=coin,
                side=normalized_side,
                timestamp_ms=timestamp_ms,
                position_id=key,
            )
            event_refs = dict(refs or {})
            event_refs.update(
                {
                    "position_id": key,
                    "fee_event_id": fee_event.event_id,
                    "fee_accounting": "SEPARATE_EVENT",
                }
            )
            event = PaperEvent.create(
                PaperEventType.POSITION_CLOSED if fully_closed else PaperEventType.POSITION_REDUCED,
                timestamp_ms=timestamp_ms,
                coin=preserve_native_instrument_symbol(coin),
                side=normalized_side,
                quantity=close_qty,
                price=float(fill_price),
                notional_usdc=notional,
                fee_usdc=fee,
                realized_pnl_usdc=gross,
                reason=reason,
                refs=event_refs,
            )
            appended_event = staged._append(event)
            staged_mark = staged.mark_to_market(
                {preserve_native_instrument_symbol(coin): float(fill_price)},
                timestamp_ms=timestamp_ms,
            )
        except (OverflowError, TypeError, ValueError):
            return self.no_trade(
                coin=coin,
                reason="EXIT_EVENT_OR_CAPITAL_INVALID",
                timestamp_ms=timestamp_ms,
                refs={"accounting_component": "CLOSE_PREVALIDATION"},
            )
        if staged_mark.event_type == PaperEventType.NO_TRADE:
            return self.no_trade(
                coin=coin,
                reason="EXIT_ACCOUNTING_NON_FINITE",
                timestamp_ms=timestamp_ms,
                refs={"staged_mark_reason": staged_mark.reason},
            )

        self.realized_pnl_usdc = staged.realized_pnl_usdc
        self._realized_pnl_exact = staged._realized_pnl_exact
        self.unrealized_pnl_usdc = staged.unrealized_pnl_usdc
        self.cash_balance_usdc = staged.cash_balance_usdc
        self._cash_balance_exact = staged._cash_balance_exact
        self.fees_paid_usdc = staged.fees_paid_usdc
        self._fees_paid_exact = staged._fees_paid_exact
        self.turnover_usdc = staged.turnover_usdc
        self._turnover_exact = staged._turnover_exact
        for current_key in tuple(self.positions):
            if current_key not in staged.positions:
                del self.positions[current_key]
        for current_key, candidate in staged.positions.items():
            current = self.positions.get(current_key)
            if current is None:
                self.positions[current_key] = candidate
            else:
                current.quantity = candidate.quantity
                current.average_entry_price = candidate.average_entry_price
                current.last_mark_price = candidate.last_mark_price
                current.leverage_effective = candidate.leverage_effective
                current.leg_notional_usd = candidate.leg_notional_usd
                current.leg_direction = candidate.leg_direction
                current.liquidation_buffer_bps = candidate.liquidation_buffer_bps
                current.last_liquidatable_price = candidate.last_liquidatable_price
        self.high_water_equity_usdc = staged.high_water_equity_usdc
        self.drawdown_usdc = staged.drawdown_usdc
        self.mark_evidence_complete = staged.mark_evidence_complete
        self.mark_evidence_gap_count = staged.mark_evidence_gap_count
        self.last_missing_mark_position_ids = staged.last_missing_mark_position_ids
        self.capital_tracker = staged.capital_tracker
        self.events.extend(staged.events[len(self.events) :])
        return appended_event

    def mark_to_market(
        self,
        marks: dict[str, float],
        *,
        timestamp_ms: int,
        liquidatable_marks: dict[str, float] | None = None,
    ) -> PaperEvent:
        active_mark_keys = {position.coin for position in self.positions.values()}
        active_liquidatable_keys = {
            key
            for position in self.positions.values()
            for key in (
                position.position_id,
                f"{position.coin}:{position.side}",
                position.coin,
            )
        }
        clean_marks: dict[str, float] = {}
        invalid_mark_keys: list[str] = []
        for raw_key, raw_value in marks.items():
            key = str(raw_key)
            if _finite_positive(raw_value):
                clean_marks[key] = float(raw_value)
            elif key in active_mark_keys:
                invalid_mark_keys.append(key)

        clean_liquidatable_marks: dict[str, float] = {}
        invalid_liquidatable_keys: list[str] = []
        for raw_key, raw_value in (liquidatable_marks or {}).items():
            key = str(raw_key)
            if _finite_positive(raw_value):
                clean_liquidatable_marks[key] = float(raw_value)
            elif key in active_liquidatable_keys:
                invalid_liquidatable_keys.append(key)

        if invalid_mark_keys or invalid_liquidatable_keys:
            return self.no_trade(
                coin=None,
                reason="MARK_INPUT_NON_FINITE",
                timestamp_ms=timestamp_ms,
                refs={
                    "invalid_mark_keys": sorted(set(invalid_mark_keys)),
                    "invalid_liquidatable_mark_keys": sorted(
                        set(invalid_liquidatable_keys)
                    ),
                },
            )

        candidate_positions: dict[str, LedgerPosition] = {}
        unrealized_values: list[float] = []
        missing_mark_ids: list[str] = []
        for key, pos in self.positions.items():
            supplied_mark = clean_marks.get(pos.coin)
            if supplied_mark is not None:
                mark_price = supplied_mark
            else:
                # Continuity diagnostics may carry the last observed mark, but
                # the proof interval is no longer eligible for strict PnL.
                missing_mark_ids.append(pos.position_id)
                mark_price = pos.last_mark_price
            candidate = replace(
                pos,
                last_mark_price=mark_price,
                last_liquidatable_price=_position_mark(
                    pos,
                    clean_liquidatable_marks,
                ),
            )
            unrealized = candidate.unrealized()
            liquidatable_unrealized = candidate.liquidatable_unrealized()
            if not math.isfinite(unrealized) or (
                liquidatable_unrealized is not None
                and not math.isfinite(liquidatable_unrealized)
            ):
                return self.no_trade(
                    coin=None,
                    reason="MARK_ACCOUNTING_NON_FINITE",
                    timestamp_ms=timestamp_ms,
                    refs={"mark_input_status": "REJECTED_NON_FINITE_PNL"},
                )
            candidate_positions[key] = candidate
            unrealized_values.append(unrealized)

        try:
            total = math.fsum(unrealized_values)
        except OverflowError:
            total = math.inf
        unrealized_total = total
        cash = float(first_not_none(self.cash_balance_usdc, 0.0))
        try:
            equity = math.fsum((cash, unrealized_total))
        except OverflowError:
            equity = math.inf
        high_water = first_not_none(self.high_water_equity_usdc, equity)
        candidate_high_water = max(float(high_water), equity)
        drawdown = max(0.0, candidate_high_water - equity)
        if not all(
            math.isfinite(value)
            for value in (total, unrealized_total, equity, candidate_high_water, drawdown)
        ):
            return self.no_trade(
                coin=None,
                reason="MARK_ACCOUNTING_NON_FINITE",
                timestamp_ms=timestamp_ms,
                refs={"mark_input_status": "REJECTED_NON_FINITE_EQUITY"},
            )
        drawdown_total = drawdown
        candidate_tracker = copy(self.capital_tracker)
        try:
            candidate_tracker.observe(
                collateral_cash_usd=cash,
                positions=tuple(
                    position.capital_input()
                    for position in candidate_positions.values()
                ),
                realized_pnl_usd=cash - self.starting_balance_usdc,
                turnover_usd=self.turnover_usdc,
            )
        except (OverflowError, ValueError):
            return self.no_trade(
                coin=None,
                reason="MARK_ACCOUNTING_NON_FINITE",
                timestamp_ms=timestamp_ms,
                refs={"mark_input_status": "REJECTED_CAPITAL_SNAPSHOT"},
            )

        sorted_missing_ids = sorted(missing_mark_ids)
        event = PaperEvent.create(
            PaperEventType.EQUITY_UPDATED,
            timestamp_ms=timestamp_ms,
            unrealized_pnl_usdc=unrealized_total,
            equity_usdc=equity,
            drawdown_usdc=drawdown_total,
            refs={
                "marks": clean_marks,
                "mark_evidence_complete": not missing_mark_ids,
                "missing_mark_position_ids": sorted_missing_ids,
                "diagnostic_last_mark_fallback_used": bool(missing_mark_ids),
            },
        )
        previous_hash = self.events[-1].event_hash if self.events else GENESIS_HASH
        try:
            seal_event(
                event.to_dict(),
                event_seq=len(self.events) + 1,
                session_id=self.session_id,
                prev_hash=str(previous_hash),
            )
        except (TypeError, ValueError, OverflowError):
            return self.no_trade(
                coin=None,
                reason="MARK_EVENT_INVALID",
                timestamp_ms=timestamp_ms,
                refs={"mark_input_status": "REJECTED_UNSERIALIZABLE_EVENT"},
            )

        # Publish the fully validated state only after both the capital
        # observation and canonical event serialization have succeeded.
        for key, candidate in candidate_positions.items():
            current = self.positions[key]
            current.last_mark_price = candidate.last_mark_price
            current.last_liquidatable_price = candidate.last_liquidatable_price
        self.last_missing_mark_position_ids = tuple(sorted_missing_ids)
        if missing_mark_ids:
            self.mark_evidence_complete = False
            self.mark_evidence_gap_count += len(missing_mark_ids)
        self.unrealized_pnl_usdc = unrealized_total
        self.high_water_equity_usdc = candidate_high_water
        self.drawdown_usdc = drawdown_total
        self.capital_tracker = candidate_tracker
        appended = self._append(event)
        return appended

    def apply_funding(
        self,
        *,
        coin: str,
        side: str,
        amount_usdc: float,
        timestamp_ms: int,
        refs: dict | None = None,
    ) -> PaperEvent:
        try:
            event_timestamp_ms = int(timestamp_ms)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("FUNDING_TIMESTAMP_INVALID") from exc

        def reject(reason: str, *, settlement_id: str | None = None) -> PaperEvent:
            safe_refs: dict[str, str] = {"accounting_component": "FUNDING"}
            if settlement_id is not None:
                safe_refs["funding_settlement_id"] = settlement_id
            return self.no_trade(
                coin=coin,
                reason=reason,
                timestamp_ms=event_timestamp_ms,
                refs=safe_refs,
            )

        try:
            funding_amount = float(amount_usdc)
        except (TypeError, ValueError, OverflowError):
            return reject("FUNDING_INVALID")
        if not math.isfinite(funding_amount):
            return reject("FUNDING_INVALID")
        try:
            funding_refs = dict(refs or {})
            settlement_id = _funding_settlement_id(funding_refs)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("FUNDING_EVIDENCE_INVALID") from exc
        if settlement_id is not None and settlement_id in self.funding_settlement_ids:
            return reject(
                "DUPLICATE_FUNDING_SETTLEMENT",
                settlement_id=settlement_id,
            )
        try:
            exact_funding = decimal_value(funding_amount)
            funding_after_exact = (
                decimal_sum((self._funding_net_exact, exact_funding))
                if exact_funding is not None
                else None
            )
            cash_after_exact = (
                decimal_sum((self._cash_balance_exact, exact_funding))
                if exact_funding is not None
                else None
            )
            funding_after = _finite_decimal_float(funding_after_exact)
            cash_after = _finite_decimal_float(cash_after_exact)
        except (TypeError, ValueError, OverflowError):
            return reject(
                "FUNDING_ACCOUNTING_NON_FINITE",
                settlement_id=settlement_id,
            )
        if funding_after is None or cash_after is None:
            return reject(
                "FUNDING_ACCOUNTING_NON_FINITE",
                settlement_id=settlement_id,
            )

        staged = copy(self)
        staged.events = list(self.events)
        staged.funding_settlement_ids = set(self.funding_settlement_ids)
        staged.capital_tracker = copy(self.capital_tracker)
        staged.funding_net_usdc = funding_after
        staged._funding_net_exact = funding_after_exact
        staged.cash_balance_usdc = cash_after
        staged._cash_balance_exact = cash_after_exact
        if settlement_id is None:
            # Retain the amount for legacy/diagnostic continuity, but never let
            # an unidentified cash flow certify economic PnL.
            staged.funding_evidence_complete = False
            funding_refs["funding_identity_status"] = "UNIDENTIFIED_DIAGNOSTIC_ONLY"
        else:
            staged.funding_settlement_ids.add(settlement_id)
            funding_refs["funding_settlement_id"] = settlement_id
            funding_refs["funding_identity_status"] = "EXACTLY_ONCE_IDENTIFIED"
        event_type = PaperEventType.FUNDING_RECEIVED if funding_amount >= 0 else PaperEventType.FUNDING_CHARGED
        try:
            event = PaperEvent.create(
                event_type,
                timestamp_ms=event_timestamp_ms,
                coin=preserve_native_instrument_symbol(coin),
                side=str(side).upper(),
                funding_usdc=funding_amount,
                refs=funding_refs,
            )
            appended = staged._append(event)
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("FUNDING_EVENT_INVALID") from exc
        try:
            staged._observe_capital()
        except (OverflowError, TypeError, ValueError):
            return reject(
                "FUNDING_EVENT_OR_CAPITAL_INVALID",
                settlement_id=settlement_id,
            )

        self.funding_net_usdc = staged.funding_net_usdc
        self._funding_net_exact = staged._funding_net_exact
        self.cash_balance_usdc = staged.cash_balance_usdc
        self._cash_balance_exact = staged._cash_balance_exact
        self.funding_evidence_complete = staged.funding_evidence_complete
        self.funding_settlement_ids.update(staged.funding_settlement_ids)
        self.capital_tracker = staged.capital_tracker
        self.events.append(appended)
        return appended

    def no_trade(
        self,
        *,
        coin: str | None,
        reason: str,
        timestamp_ms: int,
        refs: dict | None = None,
    ) -> PaperEvent:
        return self._append(
            PaperEvent.create(
                PaperEventType.NO_TRADE,
                timestamp_ms=timestamp_ms,
                coin=None if coin is None else preserve_native_instrument_symbol(coin),
                reason=reason,
                refs=refs or {},
            )
        )

    def reconciliation(
        self,
        *,
        tolerance_usdc: float = float(USD_RECONCILIATION_ABS_TOLERANCE),
    ) -> PnlReconciliation:
        return reconcile_pnl(
            starting_balance_usdc=self.starting_balance_usdc,
            realized_pnl_usdc=self.realized_pnl_usdc,
            unrealized_pnl_usdc=self.unrealized_pnl_usdc,
            fees_paid_usdc=self.fees_paid_usdc,
            funding_net_usdc=self.funding_net_usdc,
            actual_equity_usdc=self.equity_usdc,
            tolerance_usdc=tolerance_usdc,
        )

    def snapshot(self) -> dict[str, object]:
        net_pnl = self.equity_usdc - self.starting_balance_usdc
        roi_metrics = named_roi_metrics(
            pnl_usdc=net_pnl,
            initial_capital_usdc=self.starting_balance_usdc,
        )
        payload: dict[str, object] = {
            "starting_balance_usdc": _display_pnl(
                decimal_value(self.starting_balance_usdc)
            ),
            "cash_balance_usdc": _display_pnl(self._cash_balance_exact),
            "realized_pnl_usdc": _display_pnl(self._realized_pnl_exact),
            "unrealized_pnl_usdc": _display_pnl(self.unrealized_pnl_usdc),
            "fees_paid_usdc": _display_cost(self._fees_paid_exact),
            "funding_net_usdc": _display_pnl(self._funding_net_exact),
            "equity_usdc": _display_pnl(self.equity_usdc),
            "drawdown_usdc": _display_risk(self.drawdown_usdc),
            "turnover_usdc": _display_cost(self._turnover_exact),
            "economic_evidence": {
                "mark_evidence_complete": self.mark_evidence_complete,
                "mark_evidence_gap_count": self.mark_evidence_gap_count,
                "last_missing_mark_position_ids": list(self.last_missing_mark_position_ids),
                "funding_evidence_complete": self.funding_evidence_complete,
                "identified_funding_settlement_count": len(self.funding_settlement_ids),
            },
            "positions": {
                key: {
                    "coin": pos.coin,
                    "position_id": pos.position_id,
                    "side": pos.side,
                    "quantity": round(pos.quantity, 10),
                    "average_entry_price": round(pos.average_entry_price, 10),
                    "last_mark_price": round(pos.last_mark_price, 10),
                    "unrealized_pnl_usdc": _display_pnl(pos.unrealized()),
                    "liquidatable_pnl_usdc": (
                        _display_pnl(pos.liquidatable_unrealized())
                        if pos.liquidatable_unrealized() is not None
                        else None
                    ),
                    "leverage_effective": round(pos.leverage_effective, 10),
                    "leg_notional_usd": [
                        round(value, 10)
                        for value in (pos.leg_notional_usd or (pos.notional_usdc,))
                    ],
                    "leg_direction": list(
                        pos.leg_direction
                        or ((1 if pos.side == "LONG" else -1),)
                    ),
                    "liquidation_buffer_bps": pos.liquidation_buffer_bps,
                }
                for key, pos in sorted(self.positions.items())
            },
            "event_count": len(self.events),
            "session_id": self.session_id,
            "last_event_seq": self.events[-1].event_seq if self.events else 0,
            "last_event_hash": self.events[-1].event_hash if self.events else GENESIS_HASH,
            "roi": roi_metrics.to_dict(),
            "reconciliation": asdict(self.reconciliation()),
            "capital_accounting": self.capital_snapshot().to_dict(),
        }
        pnl_audit = audit_paper_ledger(
            (event.to_dict() for event in self.events),
            snapshot=payload,
        )
        payload["pnl_audit"] = pnl_audit.to_dict()
        capital = self.capital_snapshot()
        payload["authoritative_equity_usdc"] = capital.liquidatable_equity_usd
        economic_evidence_complete = (
            self.mark_evidence_complete
            and self.funding_evidence_complete
        )
        payload["strict_pnl_allowed"] = (
            pnl_audit.pnl_valid and economic_evidence_complete
        )
        payload["strict_roi_allowed"] = (
            pnl_audit.pnl_valid
            and economic_evidence_complete
            and capital.liquidatable_equity_usd is not None
        )
        return payload

    def capital_snapshot(self) -> CapitalAccountingSnapshot:
        latest = self.capital_tracker.latest
        if latest is None:
            return self._observe_capital()
        return latest

    def _observe_capital(self) -> CapitalAccountingSnapshot:
        cash = float(first_not_none(self.cash_balance_usdc, 0.0))
        return self.capital_tracker.observe(
            collateral_cash_usd=cash,
            positions=tuple(
                position.capital_input()
                for position in self.positions.values()
            ),
            realized_pnl_usd=cash - self.starting_balance_usdc,
            turnover_usd=self.turnover_usdc,
        )

    def _charge_fee(
        self,
        fee_usdc: float,
        *,
        coin: str,
        side: str,
        timestamp_ms: int,
        position_id: str,
    ) -> PaperEvent:
        if not _finite_nonnegative(fee_usdc):
            return self.no_trade(
                coin=coin,
                reason="FEE_INVALID",
                timestamp_ms=timestamp_ms,
                refs={"position_id": position_id},
            )
        fee = float(fee_usdc)
        exact_fee = decimal_value(fee)
        fees_after_exact = (
            decimal_sum((self._fees_paid_exact, exact_fee))
            if exact_fee is not None
            else None
        )
        cash_after_exact = decimal_difference(self._cash_balance_exact, exact_fee)
        fees_after = _finite_decimal_float(fees_after_exact)
        cash_after = _finite_decimal_float(cash_after_exact)
        if (
            fees_after is None
            or cash_after is None
            or fees_after_exact is None
            or cash_after_exact is None
        ):
            return self.no_trade(
                coin=coin,
                reason="FEE_ACCOUNTING_NON_FINITE",
                timestamp_ms=timestamp_ms,
                refs={"position_id": position_id},
            )
        self._fees_paid_exact = fees_after_exact
        self.fees_paid_usdc = fees_after
        self._cash_balance_exact = cash_after_exact
        self.cash_balance_usdc = cash_after
        return self._append(
            PaperEvent.create(
                PaperEventType.FEE_CHARGED,
                timestamp_ms=timestamp_ms,
                coin=preserve_native_instrument_symbol(coin),
                side=str(side).upper(),
                fee_usdc=fee,
                refs={"position_id": position_id, "accounting_component": "FEE"},
            )
        )

    def _append(self, event: PaperEvent) -> PaperEvent:
        if any(existing.event_id == event.event_id for existing in self.events):
            collision_material = (
                f"{self.session_id}|{event.event_id}|{len(self.events) + 1}"
            )
            event = replace(
                event,
                event_id="pevt:" + sha256(collision_material.encode("utf-8")).hexdigest()[:24],
            )
        previous_hash = self.events[-1].event_hash if self.events else GENESIS_HASH
        row = seal_event(
            event.to_dict(),
            event_seq=len(self.events) + 1,
            session_id=self.session_id,
            prev_hash=str(previous_hash),
        )
        sealed = replace(
            event,
            event_seq=int(row["event_seq"]),
            session_id=str(row["session_id"]),
            prev_hash=str(row["prev_hash"]),
            event_hash=str(row["event_hash"]),
        )
        self.events.append(sealed)
        return sealed

    def verify_event_chain(self) -> bool:
        verify_chain(event.to_dict() for event in self.events)
        return True

    @staticmethod
    def _key(coin: str, side: str) -> str:
        return f"{preserve_native_instrument_symbol(coin)}:{str(side).upper()}"

    @classmethod
    def _position_key(
        cls,
        coin: str,
        side: str,
        *,
        position_id: str | None,
    ) -> str:
        return str(position_id) if position_id else cls._key(coin, side)

    @staticmethod
    def event_hash(events: list[PaperEvent]) -> str:
        material = "|".join(event.event_id for event in events)
        return sha256(material.encode("utf-8")).hexdigest()


class LedgerScope(str, Enum):
    STRICT = "STRICT"
    EXPERIMENTAL = "EXPERIMENTAL"


@dataclass(slots=True)
class ScopedLedgerBook:
    """Independent capital, positions, drawdown and reports per research lane."""

    strict_starting_balance_usdc: float = 200.0
    experimental_starting_balance_usdc: float = 200.0
    session_id: str = field(default_factory=lambda: f"paper-book:{uuid.uuid4().hex}")
    _ledgers: dict[LedgerScope, PaperLedger] = field(init=False)

    def __post_init__(self) -> None:
        self._ledgers = {
            LedgerScope.STRICT: PaperLedger(
                starting_balance_usdc=float(self.strict_starting_balance_usdc),
                session_id=f"{self.session_id}:STRICT",
            ),
            LedgerScope.EXPERIMENTAL: PaperLedger(
                starting_balance_usdc=float(self.experimental_starting_balance_usdc),
                session_id=f"{self.session_id}:EXPERIMENTAL",
            ),
        }

    def ledger(self, scope: LedgerScope | str) -> PaperLedger:
        normalized = scope if isinstance(scope, LedgerScope) else LedgerScope(str(scope).upper())
        return self._ledgers[normalized]

    def snapshot(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "strict": self.ledger(LedgerScope.STRICT).snapshot(),
            "experimental": self.ledger(LedgerScope.EXPERIMENTAL).snapshot(),
            "capital_isolated": True,
            "positions_isolated": True,
            "drawdown_isolated": True,
        }


def _funding_settlement_id(refs: dict[str, object]) -> str | None:
    for key in ("funding_settlement_id", "settlement_id", "user_funding_id"):
        value = refs.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _finite_positive(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(parsed) and parsed > 0


def _finite_nonnegative(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(parsed) and parsed >= 0


def _notional_matches(
    *, quantity: object, fill_price: object, notional_usdc: object
) -> bool:
    exact_quantity = decimal_value(quantity)
    exact_price = decimal_value(fill_price)
    exact_notional = decimal_value(notional_usdc)
    if exact_quantity is None or exact_price is None or exact_notional is None:
        return False
    with localcontext() as context:
        context.prec = 80
        actual_notional = exact_quantity * exact_price
    discrepancy = decimal_difference(actual_notional, exact_notional)
    return (
        discrepancy is not None
        and discrepancy.copy_abs() <= USD_RECONCILIATION_ABS_TOLERANCE
    )


def _finite_decimal_float(value: Decimal | None) -> float | None:
    if value is None or not value.is_finite():
        return None
    try:
        result = float(value)
    except (OverflowError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _display_pnl(value: object) -> float | None:
    exact = decimal_value(value)
    if exact is None:
        return None
    return float_not_above(exact)


def _display_cost(value: object) -> float | None:
    exact = decimal_value(value)
    if exact is None:
        return None
    return float_not_below(exact)


def _display_risk(value: float) -> float | None:
    return _display_cost(value)


def _combine_leg_notionals(
    existing: tuple[float, ...],
    added: tuple[float, ...],
) -> tuple[float, ...]:
    if len(existing) != len(added):
        raise ValueError("capital leg schemas must have the same length")
    return tuple(
        float(current) + float(increment)
        for current, increment in zip(existing, added, strict=True)
    )


def _minimum_optional(
    left: float | None,
    right: float | None,
) -> float | None:
    values = [float(value) for value in (left, right) if value is not None and _finite_positive(value)]
    return min(values) if values else None


def _position_mark(
    position: LedgerPosition,
    marks: dict[str, float],
) -> float | None:
    for key in (
        position.position_id,
        f"{position.coin}:{position.side}",
        position.coin,
    ):
        value = marks.get(key)
        if _finite_positive(value):
            return float(value)
    return None


__all__ = ["LedgerPosition", "PaperLedger", "LedgerScope", "ScopedLedgerBook"]
