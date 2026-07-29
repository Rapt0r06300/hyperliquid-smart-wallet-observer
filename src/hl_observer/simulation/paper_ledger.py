from __future__ import annotations

import math
import uuid
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from hashlib import sha256

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
    starting_balance_usdc: float = 1_000.0
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
    capital_tracker: CapitalAccountingTracker = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.cash_balance_usdc is None:
            self.cash_balance_usdc = float(self.starting_balance_usdc)
        if self.high_water_equity_usdc is None:
            self.high_water_equity_usdc = float(self.starting_balance_usdc)
        self.capital_tracker = CapitalAccountingTracker(
            starting_equity_usd=self.starting_balance_usdc
        )
        self._observe_capital()

    @property
    def equity_usdc(self) -> float:
        cash = first_not_none(self.cash_balance_usdc, 0.0)
        return round(float(cash) + self.unrealized_pnl_usdc, 10)

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
            for value in (leg_notional_usd or (float(notional_usdc),))
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
            new_qty = existing.quantity + qty
            avg = ((existing.quantity * existing.average_entry_price) + (qty * fill_price)) / new_qty
            combined_legs = _combine_leg_notionals(
                existing_notionals,
                new_leg_notional,
            )
            existing_margin = sum(existing_notionals) / max(
                1.0,
                existing.leverage_effective,
            )
            added_margin = sum(new_leg_notional) / leverage
            existing.quantity = new_qty
            existing.average_entry_price = avg
            existing.last_mark_price = fill_price
            existing.leverage_effective = sum(combined_legs) / (
                existing_margin + added_margin
            )
            existing.leg_notional_usd = combined_legs
            existing.leg_direction = new_leg_direction
            existing.liquidation_buffer_bps = _minimum_optional(
                existing.liquidation_buffer_bps,
                liquidation_buffer_bps,
            )
            event_type = PaperEventType.POSITION_INCREASED
        else:
            self.positions[key] = LedgerPosition(
                position_id=key,
                coin=str(coin).upper(),
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
        self.turnover_usdc = round(
            self.turnover_usdc + sum(new_leg_notional),
            10,
        )
        fee = compute_fee_usdc(notional_usdc, fee_bps)
        fee_event = self._charge_fee(
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
            event_type,
            timestamp_ms=timestamp_ms,
            coin=str(coin).upper(),
            side=normalized_side,
            quantity=qty,
            price=float(fill_price),
            notional_usdc=float(notional_usdc),
            fee_usdc=fee,
            refs=event_refs,
        )
        appended = self._append(event)
        self._observe_capital()
        return appended

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
        close_qty = min(max(0.0, float(quantity)), pos.quantity)
        if close_qty <= 0 or fill_price <= 0:
            return self.no_trade(coin=coin, reason="EXIT_FILL_INVALID", timestamp_ms=timestamp_ms, refs=refs)
        if normalized_side == "LONG":
            gross = (float(fill_price) - pos.average_entry_price) * close_qty
        else:
            gross = (pos.average_entry_price - float(fill_price)) * close_qty
        notional = close_qty * float(fill_price)
        fee = compute_fee_usdc(notional, fee_bps)
        self.realized_pnl_usdc = round(self.realized_pnl_usdc + gross, 10)
        cash = first_not_none(self.cash_balance_usdc, 0.0)
        self.cash_balance_usdc = round(float(cash) + gross, 10)
        fee_event = self._charge_fee(
            fee,
            coin=coin,
            side=normalized_side,
            timestamp_ms=timestamp_ms,
            position_id=key,
        )
        pos.quantity -= close_qty
        pos.last_mark_price = float(fill_price)
        close_fraction = min(1.0, close_qty / max(close_qty + pos.quantity, 1e-12))
        closed_leg_notional = tuple(
            value * close_fraction
            for value in (pos.leg_notional_usd or (notional,))
        )
        self.turnover_usdc = round(
            self.turnover_usdc + sum(closed_leg_notional),
            10,
        )
        pos.leg_notional_usd = tuple(
            max(0.0, value - closed)
            for value, closed in zip(
                pos.leg_notional_usd or (notional,),
                closed_leg_notional,
                strict=True,
            )
        )
        fully_closed = pos.quantity <= 1e-12
        if fully_closed:
            del self.positions[key]
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
            coin=str(coin).upper(),
            side=normalized_side,
            quantity=close_qty,
            price=float(fill_price),
            notional_usdc=notional,
            fee_usdc=fee,
            realized_pnl_usdc=gross,
            reason=reason,
            refs=event_refs,
        )
        self._append(event)
        self.mark_to_market({str(coin).upper(): float(fill_price)}, timestamp_ms=timestamp_ms)
        return event

    def mark_to_market(
        self,
        marks: dict[str, float],
        *,
        timestamp_ms: int,
        liquidatable_marks: dict[str, float] | None = None,
    ) -> PaperEvent:
        total = 0.0
        for pos in self.positions.values():
            mark = marks.get(pos.coin, pos.last_mark_price)
            if mark and mark > 0:
                pos.last_mark_price = float(mark)
            pos.last_liquidatable_price = _position_mark(
                pos,
                liquidatable_marks or {},
            )
            total += pos.unrealized()
        self.unrealized_pnl_usdc = round(total, 10)
        equity = self.equity_usdc
        high_water = first_not_none(self.high_water_equity_usdc, equity)
        self.high_water_equity_usdc = max(float(high_water), equity)
        self.drawdown_usdc = round(max(0.0, float(self.high_water_equity_usdc) - equity), 10)
        event = PaperEvent.create(
            PaperEventType.EQUITY_UPDATED,
            timestamp_ms=timestamp_ms,
            unrealized_pnl_usdc=self.unrealized_pnl_usdc,
            equity_usdc=equity,
            drawdown_usdc=self.drawdown_usdc,
            refs={"marks": dict(marks)},
        )
        appended = self._append(event)
        self._observe_capital()
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
        self.funding_net_usdc += float(amount_usdc)
        cash = first_not_none(self.cash_balance_usdc, 0.0)
        self.cash_balance_usdc = float(cash) + float(amount_usdc)
        event_type = PaperEventType.FUNDING_RECEIVED if amount_usdc >= 0 else PaperEventType.FUNDING_CHARGED
        appended = self._append(
            PaperEvent.create(
                event_type,
                timestamp_ms=timestamp_ms,
                coin=str(coin).upper(),
                side=str(side).upper(),
                funding_usdc=float(amount_usdc),
                refs=refs or {},
            )
        )
        self._observe_capital()
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
                coin=None if coin is None else str(coin).upper(),
                reason=reason,
                refs=refs or {},
            )
        )

    def reconciliation(self, *, tolerance_usdc: float = 0.0001) -> PnlReconciliation:
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
            "starting_balance_usdc": round(self.starting_balance_usdc, 10),
            "cash_balance_usdc": round(float(first_not_none(self.cash_balance_usdc, 0.0)), 10),
            "realized_pnl_usdc": round(self.realized_pnl_usdc, 10),
            "unrealized_pnl_usdc": round(self.unrealized_pnl_usdc, 10),
            "fees_paid_usdc": round(self.fees_paid_usdc, 10),
            "funding_net_usdc": round(self.funding_net_usdc, 10),
            "equity_usdc": self.equity_usdc,
            "drawdown_usdc": self.drawdown_usdc,
            "turnover_usdc": round(self.turnover_usdc, 10),
            "positions": {
                key: {
                    "coin": pos.coin,
                    "position_id": pos.position_id,
                    "side": pos.side,
                    "quantity": round(pos.quantity, 10),
                    "average_entry_price": round(pos.average_entry_price, 10),
                    "last_mark_price": round(pos.last_mark_price, 10),
                    "unrealized_pnl_usdc": round(pos.unrealized(), 10),
                    "liquidatable_pnl_usdc": (
                        round(pos.liquidatable_unrealized(), 10)
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
        payload["strict_pnl_allowed"] = pnl_audit.pnl_valid
        payload["strict_roi_allowed"] = (
            pnl_audit.pnl_valid
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
        fee = max(0.0, float(fee_usdc))
        self.fees_paid_usdc = round(self.fees_paid_usdc + fee, 10)
        cash = first_not_none(self.cash_balance_usdc, 0.0)
        self.cash_balance_usdc = round(float(cash) - fee, 10)
        return self._append(
            PaperEvent.create(
                PaperEventType.FEE_CHARGED,
                timestamp_ms=timestamp_ms,
                coin=str(coin).upper(),
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
        return f"{str(coin).upper()}:{str(side).upper()}"

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

    strict_starting_balance_usdc: float = 1_000.0
    experimental_starting_balance_usdc: float = 1_000.0
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


def _finite_positive(value: object) -> bool:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(parsed) and parsed > 0


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
    values = [float(value) for value in (left, right) if value is not None]
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
