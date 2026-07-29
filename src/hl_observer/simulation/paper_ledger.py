from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from hashlib import sha256

from hl_observer.simulation.fee_model import compute_fee_usdc
from hl_observer.simulation.paper_event import PaperEvent, PaperEventType
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

    @property
    def notional_usdc(self) -> float:
        return abs(self.quantity) * self.average_entry_price

    def unrealized(self, mark_price: float | None = None) -> float:
        mark = float(mark_price if mark_price is not None else self.last_mark_price)
        if self.side == "LONG":
            return (mark - self.average_entry_price) * self.quantity
        return (self.average_entry_price - mark) * self.quantity


@dataclass(slots=True)
class PaperLedger:
    starting_balance_usdc: float = 1_000.0
    events: list[PaperEvent] = field(default_factory=list)
    positions: dict[str, LedgerPosition] = field(default_factory=dict)
    realized_pnl_usdc: float = 0.0
    unrealized_pnl_usdc: float = 0.0
    fees_paid_usdc: float = 0.0
    funding_net_usdc: float = 0.0
    cash_balance_usdc: float | None = None
    high_water_equity_usdc: float | None = None
    drawdown_usdc: float = 0.0

    def __post_init__(self) -> None:
        if self.cash_balance_usdc is None:
            self.cash_balance_usdc = float(self.starting_balance_usdc)
        if self.high_water_equity_usdc is None:
            self.high_water_equity_usdc = float(self.starting_balance_usdc)

    @property
    def equity_usdc(self) -> float:
        return round(float(self.cash_balance_usdc or 0.0) + self.unrealized_pnl_usdc, 10)

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
        key = self._position_key(
            coin,
            normalized_side,
            position_id=position_id,
        )
        existing = self.positions.get(key)
        if existing:
            new_qty = existing.quantity + qty
            avg = ((existing.quantity * existing.average_entry_price) + (qty * fill_price)) / new_qty
            existing.quantity = new_qty
            existing.average_entry_price = avg
            existing.last_mark_price = fill_price
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
            )
            event_type = PaperEventType.POSITION_OPENED
        fee = compute_fee_usdc(notional_usdc, fee_bps)
        self._charge_fee(fee, coin=coin, side=normalized_side, timestamp_ms=timestamp_ms)
        event = PaperEvent.create(
            event_type,
            timestamp_ms=timestamp_ms,
            coin=str(coin).upper(),
            side=normalized_side,
            quantity=qty,
            price=float(fill_price),
            notional_usdc=float(notional_usdc),
            fee_usdc=fee,
            refs=refs or {},
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
        self.cash_balance_usdc = round(float(self.cash_balance_usdc or 0.0) + gross, 10)
        self._charge_fee(fee, coin=coin, side=normalized_side, timestamp_ms=timestamp_ms)
        pos.quantity -= close_qty
        pos.last_mark_price = float(fill_price)
        fully_closed = pos.quantity <= 1e-12
        if fully_closed:
            del self.positions[key]
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
            refs=refs or {},
        )
        self._append(event)
        self.mark_to_market({str(coin).upper(): float(fill_price)}, timestamp_ms=timestamp_ms)
        return event

    def mark_to_market(self, marks: dict[str, float], *, timestamp_ms: int) -> PaperEvent:
        total = 0.0
        for pos in self.positions.values():
            mark = marks.get(pos.coin, pos.last_mark_price)
            if mark and mark > 0:
                pos.last_mark_price = float(mark)
            total += pos.unrealized()
        self.unrealized_pnl_usdc = round(total, 10)
        equity = self.equity_usdc
        self.high_water_equity_usdc = max(float(self.high_water_equity_usdc or equity), equity)
        self.drawdown_usdc = round(max(0.0, float(self.high_water_equity_usdc) - equity), 10)
        event = PaperEvent.create(
            PaperEventType.EQUITY_UPDATED,
            timestamp_ms=timestamp_ms,
            unrealized_pnl_usdc=self.unrealized_pnl_usdc,
            equity_usdc=equity,
            drawdown_usdc=self.drawdown_usdc,
            refs={"marks": dict(marks)},
        )
        return self._append(event)

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
        self.cash_balance_usdc = float(self.cash_balance_usdc or 0.0) + float(amount_usdc)
        event_type = PaperEventType.FUNDING_RECEIVED if amount_usdc >= 0 else PaperEventType.FUNDING_CHARGED
        return self._append(
            PaperEvent.create(
                event_type,
                timestamp_ms=timestamp_ms,
                coin=str(coin).upper(),
                side=str(side).upper(),
                funding_usdc=float(amount_usdc),
                refs=refs or {},
            )
        )

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
        return {
            "starting_balance_usdc": round(self.starting_balance_usdc, 10),
            "cash_balance_usdc": round(float(self.cash_balance_usdc or 0.0), 10),
            "realized_pnl_usdc": round(self.realized_pnl_usdc, 10),
            "unrealized_pnl_usdc": round(self.unrealized_pnl_usdc, 10),
            "fees_paid_usdc": round(self.fees_paid_usdc, 10),
            "funding_net_usdc": round(self.funding_net_usdc, 10),
            "equity_usdc": self.equity_usdc,
            "drawdown_usdc": self.drawdown_usdc,
            "positions": {
                key: {
                    "coin": pos.coin,
                    "position_id": pos.position_id,
                    "side": pos.side,
                    "quantity": round(pos.quantity, 10),
                    "average_entry_price": round(pos.average_entry_price, 10),
                    "last_mark_price": round(pos.last_mark_price, 10),
                    "unrealized_pnl_usdc": round(pos.unrealized(), 10),
                }
                for key, pos in sorted(self.positions.items())
            },
            "event_count": len(self.events),
            "reconciliation": asdict(self.reconciliation()),
        }

    def _charge_fee(self, fee_usdc: float, *, coin: str, side: str, timestamp_ms: int) -> None:
        fee = max(0.0, float(fee_usdc))
        self.fees_paid_usdc = round(self.fees_paid_usdc + fee, 10)
        self.cash_balance_usdc = round(float(self.cash_balance_usdc or 0.0) - fee, 10)
        self._append(
            PaperEvent.create(
                PaperEventType.FEE_CHARGED,
                timestamp_ms=timestamp_ms,
                coin=str(coin).upper(),
                side=str(side).upper(),
                fee_usdc=fee,
            )
        )

    def _append(self, event: PaperEvent) -> PaperEvent:
        self.events.append(event)
        return event

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


def _finite_positive(value: object) -> bool:
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return False
    return math.isfinite(parsed) and parsed > 0


__all__ = ["LedgerPosition", "PaperLedger"]
