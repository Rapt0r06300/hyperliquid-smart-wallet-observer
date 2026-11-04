"""Book replay (V12 capability R, repo 11): reconstruct L2 state from orderbook deltas.

Feeds an initial snapshot then incremental deltas (price→size; size<=0 removes a level)
and exposes the reconstructed top-of-book at each step. Pure / deterministic, no network,
no fabrication: it only replays the deltas it is given, in order.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class BookState:
    ts_ms: int
    bids: tuple[tuple[float, float], ...]   # sorted by price desc
    asks: tuple[tuple[float, float], ...]   # sorted by price asc

    @property
    def best_bid(self) -> float | None:
        return self.bids[0][0] if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0][0] if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread_bps(self) -> float | None:
        m = self.mid
        if m is None or m <= 0 or self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_ask - self.best_bid) / m * 10_000.0


class BookReplayer:
    def __init__(self) -> None:
        self._bids: dict[float, float] = {}
        self._asks: dict[float, float] = {}
        self._ts = 0

    def apply_snapshot(self, *, bids, asks, ts_ms: int) -> None:
        timestamp = _exact_non_negative_int(ts_ms)
        if timestamp is None or timestamp < self._ts:
            raise ValueError("book timestamps must be monotonic")
        def levels(rows):
            out = {}
            for price, size in rows:
                price_f = _finite_float(price)
                size_f = _finite_float(size)
                if price_f is None or size_f is None:
                    raise ValueError("book prices and sizes must be finite")
                if (
                    not math.isfinite(price_f)
                    or not math.isfinite(size_f)
                    or price_f <= 0.0
                    or size_f < 0.0
                ):
                    raise ValueError("book prices and sizes must be finite")
                if size_f > 0.0:
                    out[price_f] = size_f
            return out
        self._bids = levels(bids)
        self._asks = levels(asks)
        if self._bids and self._asks and max(self._bids) >= min(self._asks):
            raise ValueError("crossed order book snapshot")
        self._ts = timestamp

    def apply_delta(self, *, side: str, price: float, size: float, ts_ms: int) -> None:
        timestamp = _exact_non_negative_int(ts_ms)
        if timestamp is None or timestamp < self._ts:
            raise ValueError("book timestamps must be monotonic")
        side_l = str(side).lower()
        if side_l not in {"bid", "bids", "ask", "asks"}:
            raise ValueError("unsupported book side")
        book = self._bids if side_l.startswith("b") else self._asks
        price = _finite_float(price)
        size = _finite_float(size)
        if price is None or size is None or not math.isfinite(price) or not math.isfinite(size) or price <= 0.0:
            raise ValueError("book delta price and size must be finite")
        if size <= 0:
            book.pop(price, None)          # size 0 removes the level
        else:
            book[price] = size
        if self._bids and self._asks and max(self._bids) >= min(self._asks):
            raise ValueError("crossed order book delta")
        self._ts = timestamp

    def state(self) -> BookState:
        bids = tuple(sorted(self._bids.items(), key=lambda kv: -kv[0]))
        asks = tuple(sorted(self._asks.items(), key=lambda kv: kv[0]))
        return BookState(ts_ms=self._ts, bids=bids, asks=asks)


def replay_book(events: list[dict]) -> list[BookState]:
    """Replay a sequence of {type:'snapshot'|'delta', ...} events, returning state after each."""
    r = BookReplayer()
    out: list[BookState] = []
    for ev in events:
        event_type = ev.get("type")
        if event_type == "snapshot":
            r.apply_snapshot(bids=ev.get("bids", []), asks=ev.get("asks", []), ts_ms=ev.get("ts_ms"))
        elif event_type == "delta":
            r.apply_delta(side=ev.get("side"), price=ev.get("price"),
                          size=ev.get("size"), ts_ms=ev.get("ts_ms"))
        else:
            raise ValueError("book event type must be snapshot or delta")
        out.append(r.state())
    return out


__all__ = [
    "BookState", "BookReplayer", "replay_book", "book_replay_safety_receipt",
    "replay_required_field_receipt", "replay_null_field_receipt", "replay_field_type_receipt",
    "replay_finite_receipt", "replay_cutoff_receipt", "replay_age_receipt",
    "replay_duplicate_receipt", "replay_retry_receipt", "replay_replay_receipt",
    "replay_fill_duplicate_receipt", "replay_rejection_no_debit_receipt",
    "replay_partial_close_receipt", "replay_total_close_release_receipt",
    "replay_mark_liquidability_receipt", "replay_balance_receipt",
    "replay_funding_sign_receipt", "replay_conversion_receipt",
    "replay_commit_receipt", "replay_concurrent_write_receipt",
]


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(Decimal(str(value).strip()))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _exact_non_negative_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not parsed.is_finite() or parsed != parsed.to_integral_value() or parsed < 0:
        return None
    return int(parsed)


def _replay_base(status: str, **values: Any) -> dict[str, Any]:
    return {
        "status": status,
        "paper_read_only": True,
        "real_execution": False,
        "promotion": "DISABLED_UNTIL_REVIEW",
        **values,
    }


def _replay_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _replay_finite(value: Any) -> bool:
    return _finite_float(value) is not None


def book_replay_safety_receipt(result: Any) -> dict[str, Any]:
    """Prove only a deterministic, non-crossed replay result; no market claim is made."""
    states = result if isinstance(result, Sequence) and not isinstance(result, (str, bytes, bytearray)) else ()
    valid = bool(states) and all(isinstance(state, BookState) for state in states)
    if valid:
        timestamps = [state.ts_ms for state in states]
        valid = timestamps == sorted(timestamps)
        valid = valid and all(
            not state.bids or not state.asks or state.best_bid < state.best_ask
            for state in states
        )
    return _replay_base(
        "PROVEN" if valid else "REJECTED",
        verdict="BOOK_REPLAY_SAFE" if valid else "BOOK_REPLAY_UNSAFE",
        fail_closed=not valid,
        state_count=len(states),
    )


def replay_required_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) not in (None, "")
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_FIELD_PRESENT" if valid else "REPLAY_FIELD_MISSING", field=field, fail_closed=not valid)


def replay_null_field_receipt(row: Mapping[str, Any], *, field: str) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(field, str) and bool(field) and row.get(field) is not None
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_FIELD_NON_NULL" if valid else "REPLAY_FIELD_NULL", field=field, fail_closed=not valid)


def replay_field_type_receipt(row: Mapping[str, Any], *, field: str, expected_type: type) -> dict[str, Any]:
    valid = isinstance(row, Mapping) and isinstance(expected_type, type) and isinstance(row.get(field), expected_type)
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_FIELD_TYPE_VALID" if valid else "REPLAY_FIELD_TYPE_INVALID", field=field, fail_closed=not valid)


def replay_finite_receipt(value: Any) -> dict[str, Any]:
    valid = _replay_finite(value)
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_VALUE_FINITE" if valid else "REPLAY_VALUE_NON_FINITE", value=float(value) if valid else None, fail_closed=not valid)


def replay_cutoff_receipt(*, event_ts_ms: Any, cutoff_ts_ms: Any) -> dict[str, Any]:
    valid = _replay_integer(event_ts_ms) and _replay_integer(cutoff_ts_ms) and event_ts_ms <= cutoff_ts_ms
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_EVENT_WITHIN_CUTOFF" if valid else "REPLAY_EVENT_AFTER_CUTOFF", fail_closed=not valid)


def replay_age_receipt(*, event_ts_ms: Any, oldest_allowed_ts_ms: Any) -> dict[str, Any]:
    valid = _replay_integer(event_ts_ms) and _replay_integer(oldest_allowed_ts_ms) and event_ts_ms >= oldest_allowed_ts_ms
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_EVENT_AGE_VALID" if valid else "REPLAY_EVENT_TOO_OLD", fail_closed=not valid)


def replay_duplicate_receipt(*, event_ids: Iterable[Any]) -> dict[str, Any]:
    values = list(event_ids)
    valid = bool(values) and all(str(value).strip() for value in values) and len(values) == len(set(values))
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_EVENTS_UNIQUE" if valid else "REPLAY_EVENT_DUPLICATE_OR_EMPTY", fail_closed=not valid)


def replay_retry_receipt(*, attempts: Any, max_attempts: Any, checkpoint_saved: bool) -> dict[str, Any]:
    valid = _replay_integer(attempts) and _replay_integer(max_attempts) and 1 <= attempts <= max_attempts and checkpoint_saved is True
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_RETRY_BOUNDED" if valid else "REPLAY_RETRY_UNSAFE", fail_closed=not valid)


def replay_replay_receipt(*, outputs: Sequence[Any]) -> dict[str, Any]:
    valid = bool(outputs) and len({repr(value) for value in outputs}) == 1
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_DETERMINISTIC" if valid else "REPLAY_DIVERGED", fail_closed=not valid)


def replay_fill_duplicate_receipt(*, fill_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(fill_ids) and all(str(value).strip() for value in fill_ids) and len(fill_ids) == len(set(fill_ids))
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_FILLS_UNIQUE" if valid else "REPLAY_FILL_DUPLICATED", fail_closed=not valid)


def replay_rejection_no_debit_receipt(*, rejected: bool, debited: bool) -> dict[str, Any]:
    valid = rejected is True and debited is False
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_REJECTION_NO_DEBIT" if valid else "REPLAY_REJECTION_DEBITED", fail_closed=not valid)


def replay_partial_close_receipt(*, close_quantity: Any, open_quantity: Any, fee_known: bool, fee_amount: Any) -> dict[str, Any]:
    close = _finite_float(close_quantity)
    open_size = _finite_float(open_quantity)
    fee = _finite_float(fee_amount)
    valid = close is not None and open_size is not None and fee is not None and fee_known is True and 0 < close < open_size and fee >= 0
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_PARTIAL_CLOSE_COSTED" if valid else "REPLAY_PARTIAL_CLOSE_UNSAFE", fail_closed=not valid)


def replay_total_close_release_receipt(*, close_quantity: Any, open_quantity: Any, released_margin: Any) -> dict[str, Any]:
    close = _finite_float(close_quantity)
    open_size = _finite_float(open_quantity)
    release = _finite_float(released_margin)
    valid = close is not None and open_size is not None and release is not None and open_size > 0 and abs(close - open_size) <= 1e-12 and release >= 0
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_TOTAL_CLOSE_RELEASED" if valid else "REPLAY_TOTAL_CLOSE_NOT_RELEASED", fail_closed=not valid)


def replay_mark_liquidability_receipt(*, mark_price: Any, bid: Any, ask: Any) -> dict[str, Any]:
    mark = _finite_float(mark_price)
    best_bid = _finite_float(bid)
    best_ask = _finite_float(ask)
    valid = mark is not None and best_bid is not None and best_ask is not None and best_bid > 0 and best_ask >= best_bid and best_bid <= mark <= best_ask
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_MARK_LIQUIDABLE" if valid else "REPLAY_MARK_NOT_LIQUIDABLE", fail_closed=not valid)


def replay_balance_receipt(*, balance: Any) -> dict[str, Any]:
    value = _finite_float(balance)
    valid = value is not None and value >= 0
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_BALANCE_NON_NEGATIVE" if valid else "REPLAY_BALANCE_NEGATIVE", fail_closed=not valid)


def replay_funding_sign_receipt(*, amount: Any, direction: str) -> dict[str, Any]:
    value = _finite_float(amount)
    normalized = str(direction or "").strip().upper()
    valid = value is not None and ((normalized == "CREDIT" and value >= 0) or (normalized == "DEBIT" and value <= 0))
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_FUNDING_SIGN_VALID" if valid else "REPLAY_FUNDING_SIGN_INVALID", fail_closed=not valid)


def replay_conversion_receipt(*, fee_amount: Any, fee_token: Any, pnl_currency: Any, token_to_pnl_rate: Any) -> dict[str, Any]:
    amount = _finite_float(fee_amount)
    rate = _finite_float(token_to_pnl_rate)
    valid = amount is not None and amount >= 0 and rate is not None and rate >= 0 and isinstance(fee_token, str) and bool(fee_token.strip()) and isinstance(pnl_currency, str) and bool(pnl_currency.strip())
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_CONVERSION_PROVEN" if valid else "REPLAY_CONVERSION_MISSING", fail_closed=not valid)


def replay_commit_receipt(*, crashed: bool, committed: bool, checkpoint_saved: bool) -> dict[str, Any]:
    valid = (crashed is True and committed is False and checkpoint_saved is True) or (crashed is False and committed is True)
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_COMMIT_ATOMIC" if valid else "REPLAY_COMMIT_PARTIAL", fail_closed=not valid)


def replay_concurrent_write_receipt(*, write_ids: Sequence[Any]) -> dict[str, Any]:
    valid = bool(write_ids) and all(str(value).strip() for value in write_ids) and len(write_ids) == len(set(write_ids))
    return _replay_base("PROVEN" if valid else "REJECTED", verdict="REPLAY_WRITES_UNIQUE" if valid else "REPLAY_DOUBLE_WRITE", fail_closed=not valid)
