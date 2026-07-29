"""Causal executable-price and fill replay from canonical market events.

The replay only consumes events that were durably observable after the signal
and configured latency. It never fills at a mid price and never extrapolates
beyond visible L2 depth. Diagnostic spread, slippage, latency and adverse
selection costs are reported separately so embedded price costs are not
charged twice by the paper ledger.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Iterable, Mapping


class FillStatus(str, Enum):
    FILLED = "FILLED"
    PARTIAL = "PARTIAL"
    NO_FILL = "NO_FILL"
    NO_BOOK = "NO_BOOK"
    STALE_BOOK = "STALE_BOOK"
    QUALITY_BLOCKED = "QUALITY_BLOCKED"
    INVALID_INTENT = "INVALID_INTENT"
    UNMEASURABLE = "UNMEASURABLE"


@dataclass(frozen=True, slots=True)
class ReplayIntent:
    signal_id: str
    coin: str
    position_side: str
    action: str
    signal_observable_at_ms: int
    requested_notional_usdc: float | None = None
    requested_quantity: float | None = None
    latency_ms: int = 250
    execution_style: str = "TAKER"
    limit_price: float | None = None
    maker_timeout_ms: int = 5_000
    extra_queue_ahead_quantity: float = 0.0
    fee_bps: float = 4.5
    min_feed_quality_score: float = 75.0
    max_book_wait_ms: int = 2_000
    adverse_selection_horizon_ms: int = 5_000


@dataclass(frozen=True, slots=True)
class ExecutionCosts:
    fee_bps: float
    fee_usdc: float
    spread_bps: float | None
    depth_slippage_bps: float | None
    latency_cost_bps: float | None
    markout_bps: float | None
    adverse_selection_bps: float | None
    embedded_in_fill_price_bps: float | None
    cash_charged_separately_usdc: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ExecutableFill:
    status: FillStatus
    reason: str
    signal_id: str
    coin: str
    position_side: str
    action: str
    exchange_action: str
    requested_notional_usdc: float
    requested_quantity: float
    filled_notional_usdc: float
    filled_quantity: float
    fill_ratio: float
    fill_price: float | None
    best_price: float | None
    book_mid: float | None
    executed_at_ms: int | None
    observed_latency_ms: int | None
    source_event_id: str | None
    source_tick_ref: str | None
    feed_quality_score: float | None
    queue_ahead_quantity: float | None
    matched_trade_quantity: float | None
    costs: ExecutionCosts

    @property
    def executable(self) -> bool:
        return self.status in {FillStatus.FILLED, FillStatus.PARTIAL}

    def as_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["status"] = self.status.value
        row["costs"] = self.costs.as_dict()
        row["paper_only"] = True
        row["real_execution"] = False
        return row


@dataclass(frozen=True, slots=True)
class _Book:
    event: Mapping[str, Any]
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]

    @property
    def observed_at_ms(self) -> int:
        return int(self.event.get("observable_at_ms") or 0)

    @property
    def best_bid(self) -> float:
        return self.bids[0][0]

    @property
    def best_ask(self) -> float:
        return self.asks[0][0]

    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2.0


def replay_executable_fill(
    intent: ReplayIntent,
    canonical_events: Iterable[Mapping[str, Any] | Any],
) -> ExecutableFill:
    """Replay one taker or conservative FIFO maker fill."""
    events = sorted(
        (_event_row(event) for event in canonical_events),
        key=lambda row: (int(row.get("observable_at_ms") or 0), str(row.get("event_id") or "")),
    )
    invalid = _validate_intent(intent)
    if invalid:
        return _empty_fill(intent, FillStatus.INVALID_INTENT, invalid)

    target_ms = int(intent.signal_observable_at_ms) + max(0, int(intent.latency_ms))
    books = [
        book
        for event in events
        if (book := _book_from_event(event, coin=intent.coin)) is not None
    ]
    eligible_books = [book for book in books if book.observed_at_ms >= target_ms]
    if not eligible_books:
        return _empty_fill(intent, FillStatus.NO_BOOK, "NO_OBSERVABLE_L2_AFTER_LATENCY")

    book = eligible_books[0]
    wait_ms = book.observed_at_ms - target_ms
    if wait_ms > max(0, int(intent.max_book_wait_ms)):
        return _empty_fill(
            intent,
            FillStatus.STALE_BOOK,
            "FIRST_OBSERVABLE_BOOK_TOO_LATE",
            book=book,
        )
    quality = _to_float(book.event.get("feed_quality_score"))
    if (
        not bool(book.event.get("data_gate_ready"))
        or quality is None
        or quality < float(intent.min_feed_quality_score)
    ):
        return _empty_fill(
            intent,
            FillStatus.QUALITY_BLOCKED,
            "DATA_QUALITY_GATE_BLOCKED",
            book=book,
        )

    if str(intent.execution_style).upper() == "MAKER":
        raw_fill = _replay_maker(intent, events, book)
    else:
        raw_fill = _replay_taker(intent, book)
    if not raw_fill.executable:
        return raw_fill

    return _with_diagnostics(
        raw_fill,
        intent=intent,
        books=books,
    )


def _validate_intent(intent: ReplayIntent) -> str | None:
    if not str(intent.signal_id).strip() or not str(intent.coin).strip():
        return "MISSING_SIGNAL_OR_COIN"
    if str(intent.position_side).upper() not in {"LONG", "SHORT"}:
        return "INVALID_POSITION_SIDE"
    if str(intent.action).upper() not in {"OPEN", "ADD", "INCREASE", "REDUCE", "CLOSE"}:
        return "INVALID_ACTION"
    if (
        (intent.requested_notional_usdc is None or intent.requested_notional_usdc <= 0)
        and (intent.requested_quantity is None or intent.requested_quantity <= 0)
    ):
        return "MISSING_POSITIVE_SIZE"
    if str(intent.execution_style).upper() not in {"TAKER", "MAKER"}:
        return "INVALID_EXECUTION_STYLE"
    if str(intent.execution_style).upper() == "MAKER" and not (
        intent.limit_price is not None and intent.limit_price > 0
    ):
        return "MAKER_LIMIT_PRICE_REQUIRED"
    return None


def _exchange_action(intent: ReplayIntent) -> str:
    side = str(intent.position_side).upper()
    entry = str(intent.action).upper() in {"OPEN", "ADD", "INCREASE"}
    if (entry and side == "LONG") or (not entry and side == "SHORT"):
        return "BUY"
    return "SELL"


def _replay_taker(intent: ReplayIntent, book: _Book) -> ExecutableFill:
    exchange_action = _exchange_action(intent)
    levels = book.asks if exchange_action == "BUY" else book.bids
    best = levels[0][0]
    target_qty = (
        float(intent.requested_quantity)
        if intent.requested_quantity is not None
        else None
    )
    target_notional = (
        float(intent.requested_notional_usdc)
        if intent.requested_notional_usdc is not None
        else None
    )
    remaining_qty = target_qty
    remaining_notional = target_notional
    filled_qty = 0.0
    filled_notional = 0.0
    for price, quantity in levels:
        if remaining_qty is not None:
            take_qty = min(remaining_qty, quantity)
        else:
            take_qty = min(quantity, float(remaining_notional or 0.0) / price)
        if take_qty <= 0:
            continue
        filled_qty += take_qty
        filled_notional += take_qty * price
        if remaining_qty is not None:
            remaining_qty -= take_qty
            if remaining_qty <= 1e-12:
                break
        else:
            remaining_notional = max(0.0, float(remaining_notional or 0.0) - take_qty * price)
            if remaining_notional <= 1e-8:
                break
    requested_qty = target_qty or (
        float(target_notional or 0.0) / best if best > 0 else 0.0
    )
    requested_notional = target_notional or requested_qty * best
    ratio = min(
        1.0,
        (
            filled_qty / requested_qty
            if target_qty is not None and requested_qty > 0
            else filled_notional / requested_notional
            if requested_notional > 0
            else 0.0
        ),
    )
    status = (
        FillStatus.FILLED
        if ratio >= 1.0 - 1e-9
        else FillStatus.PARTIAL
        if filled_qty > 0
        else FillStatus.NO_FILL
    )
    fill_price = filled_notional / filled_qty if filled_qty > 0 else None
    return _build_fill(
        intent,
        book=book,
        status=status,
        reason=(
            "VISIBLE_DEPTH_FILLED"
            if status == FillStatus.FILLED
            else "VISIBLE_DEPTH_PARTIAL"
            if status == FillStatus.PARTIAL
            else "NO_VISIBLE_DEPTH"
        ),
        exchange_action=exchange_action,
        requested_notional=requested_notional,
        requested_quantity=requested_qty,
        filled_notional=filled_notional,
        filled_quantity=filled_qty,
        fill_price=fill_price,
        best_price=best,
        queue_ahead=None,
        matched_trade_quantity=None,
    )


def _replay_maker(
    intent: ReplayIntent,
    events: list[Mapping[str, Any]],
    book: _Book,
) -> ExecutableFill:
    exchange_action = _exchange_action(intent)
    limit_price = float(intent.limit_price or 0.0)
    own_side = book.bids if exchange_action == "BUY" else book.asks
    visible_queue = next(
        (quantity for price, quantity in own_side if abs(price - limit_price) <= 1e-12),
        None,
    )
    if visible_queue is None:
        return _empty_fill(
            intent,
            FillStatus.UNMEASURABLE,
            "LIMIT_PRICE_NOT_VISIBLE_IN_SNAPSHOT",
            book=book,
        )
    requested_qty = (
        float(intent.requested_quantity)
        if intent.requested_quantity is not None
        else float(intent.requested_notional_usdc or 0.0) / limit_price
    )
    requested_notional = (
        float(intent.requested_notional_usdc)
        if intent.requested_notional_usdc is not None
        else requested_qty * limit_price
    )
    queue_ahead = visible_queue + max(0.0, float(intent.extra_queue_ahead_quantity))
    deadline = book.observed_at_ms + max(0, int(intent.maker_timeout_ms))
    matching_flow = 0.0
    for event in events:
        observed_at = int(event.get("observable_at_ms") or 0)
        if observed_at <= book.observed_at_ms or observed_at > deadline:
            continue
        if str(event.get("instrument") or "").upper() != str(intent.coin).upper():
            continue
        if str(event.get("event_type") or "") != "PUBLIC_TRADE_BATCH":
            continue
        for trade in _trades_from_event(event):
            price = _to_float(trade.get("px"))
            quantity = _to_float(trade.get("sz"))
            aggressor = str(trade.get("side") or "").upper()
            if price is None or quantity is None:
                continue
            matches = (
                exchange_action == "BUY"
                and aggressor == "A"
                and price <= limit_price
            ) or (
                exchange_action == "SELL"
                and aggressor == "B"
                and price >= limit_price
            )
            if matches:
                matching_flow += quantity
    filled_qty = min(requested_qty, max(0.0, matching_flow - queue_ahead))
    ratio = min(1.0, filled_qty / requested_qty) if requested_qty > 0 else 0.0
    status = (
        FillStatus.FILLED
        if ratio >= 1.0 - 1e-9
        else FillStatus.PARTIAL
        if filled_qty > 0
        else FillStatus.NO_FILL
    )
    return _build_fill(
        intent,
        book=book,
        status=status,
        reason=(
            "FIFO_PUBLIC_TRADES_FILLED"
            if status == FillStatus.FILLED
            else "FIFO_PUBLIC_TRADES_PARTIAL"
            if status == FillStatus.PARTIAL
            else "FIFO_QUEUE_NOT_DEPLETED"
        ),
        exchange_action=exchange_action,
        requested_notional=requested_notional,
        requested_quantity=requested_qty,
        filled_notional=filled_qty * limit_price,
        filled_quantity=filled_qty,
        fill_price=limit_price if filled_qty > 0 else None,
        best_price=book.best_bid if exchange_action == "BUY" else book.best_ask,
        queue_ahead=queue_ahead,
        matched_trade_quantity=matching_flow,
    )


def _build_fill(
    intent: ReplayIntent,
    *,
    book: _Book,
    status: FillStatus,
    reason: str,
    exchange_action: str,
    requested_notional: float,
    requested_quantity: float,
    filled_notional: float,
    filled_quantity: float,
    fill_price: float | None,
    best_price: float | None,
    queue_ahead: float | None,
    matched_trade_quantity: float | None,
) -> ExecutableFill:
    ratio = (
        min(1.0, filled_quantity / requested_quantity)
        if requested_quantity > 0
        else 0.0
    )
    fee_bps = max(0.0, float(intent.fee_bps))
    fee = max(0.0, filled_notional) * fee_bps / 10_000.0
    spread_bps = (
        (book.best_ask - book.best_bid) / book.mid * 10_000.0
        if book.mid > 0
        else None
    )
    slip = None
    if fill_price is not None and best_price and best_price > 0:
        direction = 1.0 if exchange_action == "BUY" else -1.0
        slip = max(0.0, direction * (fill_price - best_price) / best_price * 10_000.0)
    costs = ExecutionCosts(
        fee_bps=fee_bps,
        fee_usdc=fee,
        spread_bps=spread_bps,
        depth_slippage_bps=slip,
        latency_cost_bps=None,
        markout_bps=None,
        adverse_selection_bps=None,
        embedded_in_fill_price_bps=slip,
        cash_charged_separately_usdc=fee,
    )
    return ExecutableFill(
        status=status,
        reason=reason,
        signal_id=intent.signal_id,
        coin=str(intent.coin).upper(),
        position_side=str(intent.position_side).upper(),
        action=str(intent.action).upper(),
        exchange_action=exchange_action,
        requested_notional_usdc=requested_notional,
        requested_quantity=requested_quantity,
        filled_notional_usdc=filled_notional,
        filled_quantity=filled_quantity,
        fill_ratio=ratio,
        fill_price=fill_price,
        best_price=best_price,
        book_mid=book.mid,
        executed_at_ms=book.observed_at_ms if fill_price is not None else None,
        observed_latency_ms=book.observed_at_ms - int(intent.signal_observable_at_ms),
        source_event_id=str(book.event.get("event_id") or ""),
        source_tick_ref=str(book.event.get("source_tick_ref") or ""),
        feed_quality_score=_to_float(book.event.get("feed_quality_score")),
        queue_ahead_quantity=queue_ahead,
        matched_trade_quantity=matched_trade_quantity,
        costs=costs,
    )


def _with_diagnostics(
    fill: ExecutableFill,
    *,
    intent: ReplayIntent,
    books: list[_Book],
) -> ExecutableFill:
    fill_book = next(
        (book for book in books if book.event.get("event_id") == fill.source_event_id),
        None,
    )
    if fill_book is None:
        return fill
    baseline = next(
        (
            book
            for book in books
            if book.observed_at_ms >= int(intent.signal_observable_at_ms)
            and book.observed_at_ms <= fill_book.observed_at_ms
        ),
        None,
    )
    future_target = fill_book.observed_at_ms + max(
        0, int(intent.adverse_selection_horizon_ms)
    )
    future = next((book for book in books if book.observed_at_ms >= future_target), None)
    position_sign = 1.0 if str(intent.position_side).upper() == "LONG" else -1.0
    latency_cost = None
    if baseline is not None and baseline.mid > 0:
        move = position_sign * (fill_book.mid - baseline.mid) / baseline.mid * 10_000.0
        latency_cost = max(0.0, -move)
    markout = None
    adverse = None
    if future is not None and fill_book.mid > 0:
        markout = position_sign * (future.mid - fill_book.mid) / fill_book.mid * 10_000.0
        adverse = max(0.0, -markout)
    embedded = sum(
        value
        for value in (
            fill.costs.depth_slippage_bps,
            latency_cost,
        )
        if value is not None
    )
    costs = ExecutionCosts(
        fee_bps=fill.costs.fee_bps,
        fee_usdc=fill.costs.fee_usdc,
        spread_bps=fill.costs.spread_bps,
        depth_slippage_bps=fill.costs.depth_slippage_bps,
        latency_cost_bps=latency_cost,
        markout_bps=markout,
        adverse_selection_bps=adverse,
        embedded_in_fill_price_bps=embedded,
        cash_charged_separately_usdc=fill.costs.fee_usdc,
    )
    values = {field: getattr(fill, field) for field in fill.__dataclass_fields__}
    values["costs"] = costs
    return ExecutableFill(**values)


def _empty_fill(
    intent: ReplayIntent,
    status: FillStatus,
    reason: str,
    *,
    book: _Book | None = None,
) -> ExecutableFill:
    exchange_action = _exchange_action(intent)
    requested_qty = max(0.0, float(intent.requested_quantity or 0.0))
    requested_notional = max(0.0, float(intent.requested_notional_usdc or 0.0))
    return ExecutableFill(
        status=status,
        reason=reason,
        signal_id=str(intent.signal_id),
        coin=str(intent.coin).upper(),
        position_side=str(intent.position_side).upper(),
        action=str(intent.action).upper(),
        exchange_action=exchange_action,
        requested_notional_usdc=requested_notional,
        requested_quantity=requested_qty,
        filled_notional_usdc=0.0,
        filled_quantity=0.0,
        fill_ratio=0.0,
        fill_price=None,
        best_price=None,
        book_mid=book.mid if book is not None else None,
        executed_at_ms=None,
        observed_latency_ms=(
            book.observed_at_ms - int(intent.signal_observable_at_ms)
            if book is not None
            else None
        ),
        source_event_id=(
            str(book.event.get("event_id") or "") if book is not None else None
        ),
        source_tick_ref=(
            str(book.event.get("source_tick_ref") or "") if book is not None else None
        ),
        feed_quality_score=(
            _to_float(book.event.get("feed_quality_score"))
            if book is not None
            else None
        ),
        queue_ahead_quantity=None,
        matched_trade_quantity=None,
        costs=ExecutionCosts(
            fee_bps=max(0.0, float(intent.fee_bps)),
            fee_usdc=0.0,
            spread_bps=None,
            depth_slippage_bps=None,
            latency_cost_bps=None,
            markout_bps=None,
            adverse_selection_bps=None,
            embedded_in_fill_price_bps=None,
            cash_charged_separately_usdc=0.0,
        ),
    )


def _event_row(event: Mapping[str, Any] | Any) -> Mapping[str, Any]:
    if isinstance(event, Mapping):
        return event
    as_dict = getattr(event, "as_dict", None)
    if callable(as_dict):
        return as_dict()
    raise TypeError("canonical event must be a mapping or expose as_dict()")


def _book_from_event(event: Mapping[str, Any], *, coin: str) -> _Book | None:
    if str(event.get("event_type") or "") != "L2_BOOK_SNAPSHOT":
        return None
    if str(event.get("instrument") or "").upper() != str(coin).upper():
        return None
    payload = event.get("raw_payload")
    if not isinstance(payload, Mapping):
        return None
    data = payload.get("data")
    if not isinstance(data, Mapping):
        return None
    levels = data.get("levels")
    if not isinstance(levels, list) or len(levels) < 2:
        return None
    bids = _levels(levels[0])
    asks = _levels(levels[1])
    if not bids or not asks or bids[0][0] > asks[0][0]:
        return None
    return _Book(event=event, bids=tuple(bids), asks=tuple(asks))


def _levels(raw_levels: Any) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    if not isinstance(raw_levels, list):
        return result
    for level in raw_levels:
        if isinstance(level, Mapping):
            price = _to_float(level.get("px"))
            quantity = _to_float(level.get("sz"))
        elif isinstance(level, (list, tuple)) and len(level) >= 2:
            price = _to_float(level[0])
            quantity = _to_float(level[1])
        else:
            continue
        if price is not None and quantity is not None and price > 0 and quantity > 0:
            result.append((price, quantity))
    return result


def _trades_from_event(event: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    payload = event.get("raw_payload")
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    return [trade for trade in data if isinstance(trade, Mapping)]


def _to_float(value: Any) -> float | None:
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    if converted != converted:
        return None
    return converted


__all__ = [
    "ExecutableFill",
    "ExecutionCosts",
    "FillStatus",
    "ReplayIntent",
    "replay_executable_fill",
]
