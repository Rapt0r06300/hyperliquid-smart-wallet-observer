from __future__ import annotations

import math


def partial_fill_ratio(order_notional_usdc: float, orderbook_depth_usdc: float) -> float:
    if order_notional_usdc <= 0:
        return 0.0
    if orderbook_depth_usdc <= 0:
        return 0.0
    return min(1.0, orderbook_depth_usdc / order_notional_usdc)


def maker_partial_fill_receipt(*, order_notional_usdc: object, observed_depth_usdc: object) -> dict[str, object]:
    """Report partial fill from observed depth, never from a price touch."""

    try:
        order, depth = float(order_notional_usdc), float(observed_depth_usdc)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "reason": "NOTIONAL_INVALID"}
    if not all(math.isfinite(value) for value in (order, depth)) or order <= 0.0 or depth < 0.0:
        return {"status": "UNMEASURABLE", "reason": "NOTIONAL_INVALID"}
    ratio = partial_fill_ratio(order, depth)
    return {"status": "PROVEN", "fill_ratio": round(ratio, 8), "partial": bool(0.0 < ratio < 1.0), "filled": bool(ratio > 0.0)}


def acceptance_before_fill(*, accepted_ts_ms: object, fill_ts_ms: object) -> dict[str, object]:
    """A paper fill cannot precede the simulated acceptance event."""

    if isinstance(accepted_ts_ms, bool) or isinstance(fill_ts_ms, bool):
        return {"status": "UNMEASURABLE", "accepted": False, "reason": "TIMESTAMP_INVALID"}
    try:
        accepted_raw, filled_raw = float(accepted_ts_ms), float(fill_ts_ms)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "accepted": False, "reason": "TIMESTAMP_INVALID"}
    if not all(math.isfinite(value) and value.is_integer() for value in (accepted_raw, filled_raw)):
        return {"status": "UNMEASURABLE", "accepted": False, "reason": "TIMESTAMP_INVALID"}
    accepted, filled = int(accepted_raw), int(filled_raw)
    if accepted < 0 or filled < 0:
        return {"status": "UNMEASURABLE", "accepted": False, "reason": "TIMESTAMP_INVALID"}
    return {"status": "PROVEN", "accepted": filled >= accepted, "reason": "OK" if filled >= accepted else "FILL_BEFORE_ACCEPTANCE"}


def _level_parts(level: object, *, expected_book_side: str | None = None) -> tuple[float, float] | None:
    if isinstance(level, dict):
        status = str(level.get("status", level.get("event", ""))).casefold()
        if status in {"cancel", "cancelled", "canceled", "reject", "rejected", "open", "modify", "modified"}:
            return None
        declared_side = str(level.get("book_side", level.get("side", ""))).casefold()
        if declared_side and expected_book_side and declared_side not in {expected_book_side, "buy" if expected_book_side == "ask" else "sell"}:
            return None
        raw_price, raw_size = level.get("px", level.get("price")), level.get("sz", level.get("size"))
    elif isinstance(level, (list, tuple)) and len(level) >= 2:
        raw_price, raw_size = level[0], level[1]
    else:
        return None
    try:
        price, size = float(raw_price), float(raw_size)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(price) or not math.isfinite(size) or price <= 0 or size <= 0:
        return None
    return price, size


def market_depth_fill_receipt(
    *,
    side: object,
    order_notional_usdc: object,
    levels: object,
    externally_consumed_by_id: dict[str, object] | None = None,
) -> dict[str, object]:
    """Walk observed executable depth; never fill at a theoretical mid."""

    if not isinstance(side, str) or side.casefold() not in {"buy", "sell", "long", "short"}:
        return {"status": "UNMEASURABLE", "filled": False, "reason": "SIDE_INVALID"}
    try:
        requested = float(order_notional_usdc)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "filled": False, "reason": "NOTIONAL_INVALID"}
    if not math.isfinite(requested) or requested <= 0 or not isinstance(levels, (list, tuple)) or not levels:
        return {"status": "UNMEASURABLE", "filled": False, "reason": "DEPTH_MISSING_OR_INVALID"}
    expected_book_side = "bid" if side.casefold() in {"sell", "short"} else "ask"
    parsed: list[tuple[float, float]] = []
    for level in levels:
        part = _level_parts(level, expected_book_side=expected_book_side)
        if part is None:
            continue
        if externally_consumed_by_id and isinstance(level, dict):
            native_id = str(level.get("native_id", level.get("id", ""))).strip()
            if native_id and native_id in externally_consumed_by_id:
                try:
                    consumed = float(externally_consumed_by_id[native_id])
                except (TypeError, ValueError, OverflowError):
                    return {"status": "UNMEASURABLE", "filled": False, "reason": "EXTERNAL_CONSUMPTION_INVALID"}
                if not math.isfinite(consumed) or consumed < 0:
                    return {"status": "UNMEASURABLE", "filled": False, "reason": "EXTERNAL_CONSUMPTION_INVALID"}
                part = (part[0], max(0.0, part[1] - consumed))
        if part[1] > 0:
            parsed.append(part)
    if not parsed:
        return {"status": "UNMEASURABLE", "filled": False, "reason": "DEPTH_MISSING_OR_INVALID"}
    reverse = side.casefold() in {"sell", "short"}
    parsed.sort(key=lambda item: item[0], reverse=reverse)
    remaining = requested
    filled_notional = 0.0
    quantity = 0.0
    for price, size in parsed:
        level_notional = price * size
        consumed = min(remaining, level_notional)
        filled_notional += consumed
        quantity += consumed / price
        remaining -= consumed
        if remaining <= 1e-12:
            break
    if filled_notional <= 0:
        return {"status": "PROVEN", "filled": False, "reason": "NO_EXECUTABLE_DEPTH", "filled_notional_usdc": 0.0}
    return {
        "status": "PROVEN",
        "filled": True,
        "partial": remaining > 1e-12,
        "requested_notional_usdc": requested,
        "filled_notional_usdc": round(filled_notional, 12),
        "quantity": round(quantity, 12),
        "vwap": filled_notional / quantity,
        "remaining_notional_usdc": max(0.0, remaining),
        "paper_read_only": True,
    }


def exit_fill_from_depth_receipt(*, side: object, quantity: object, levels: object) -> dict[str, object]:
    """Price liquidation from executable exit levels, never from a mid price."""

    try:
        requested_quantity = float(quantity)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "filled": False, "reason": "QUANTITY_INVALID"}
    if not math.isfinite(requested_quantity) or requested_quantity <= 0:
        return {"status": "UNMEASURABLE", "filled": False, "reason": "QUANTITY_INVALID"}
    if not isinstance(levels, (list, tuple)) or not levels:
        return {"status": "UNMEASURABLE", "filled": False, "reason": "EXIT_DEPTH_MISSING"}
    if not isinstance(side, str) or side.casefold() not in {"buy", "sell", "long", "short"}:
        return {"status": "UNMEASURABLE", "filled": False, "reason": "SIDE_INVALID"}
    expected = "bid" if side.casefold() in {"sell", "short"} else "ask"
    parsed = [part for level in levels if (part := _level_parts(level, expected_book_side=expected)) is not None]
    if not parsed:
        return {"status": "UNMEASURABLE", "filled": False, "reason": "EXIT_DEPTH_MISSING"}
    parsed.sort(key=lambda item: item[0], reverse=expected == "bid")
    remaining = requested_quantity
    filled_quantity = 0.0
    proceeds = 0.0
    for price, size in parsed:
        consumed = min(remaining, size)
        filled_quantity += consumed
        proceeds += consumed * price
        remaining -= consumed
        if remaining <= 1e-12:
            break
    if filled_quantity <= 0:
        return {"status": "PROVEN", "filled": False, "reason": "NO_EXECUTABLE_EXIT_DEPTH"}
    return {
        "status": "PROVEN",
        "filled": True,
        "partial": remaining > 1e-12,
        "requested_quantity": requested_quantity,
        "filled_quantity": filled_quantity,
        "remaining_quantity": max(0.0, remaining),
        "vwap": proceeds / filled_quantity,
        "paper_read_only": True,
    }


def cash_delta_receipt(*, side: object, filled_notional_usdc: object, fee_bps: object, cash_before_usdc: object) -> dict[str, object]:
    """Apply observed partial-fill cash impact exactly once, including fees."""

    if not isinstance(side, str) or side.casefold() not in {"buy", "sell", "long", "short"}:
        return {"status": "UNMEASURABLE", "reason": "SIDE_INVALID"}
    try:
        filled, fee, cash_before = float(filled_notional_usdc), float(fee_bps), float(cash_before_usdc)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "reason": "CASH_INPUT_INVALID"}
    if not all(math.isfinite(value) for value in (filled, fee, cash_before)) or filled < 0 or fee < 0:
        return {"status": "UNMEASURABLE", "reason": "CASH_INPUT_INVALID"}
    fee_usdc = filled * fee / 10_000.0
    delta = -(filled + fee_usdc) if side.casefold() in {"buy", "long"} else filled - fee_usdc
    return {"status": "PROVEN", "cash_delta_usdc": delta, "cash_after_usdc": cash_before + delta, "fee_usdc": fee_usdc, "paper_read_only": True}


def minimum_notional_receipt(*, raw_notional_usdc: object, rounded_notional_usdc: object, minimum_notional_usdc: object) -> dict[str, object]:
    """Reject an order when rounding leaves the actual submitted notional below minimum."""

    try:
        raw, rounded, minimum = float(raw_notional_usdc), float(rounded_notional_usdc), float(minimum_notional_usdc)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "accepted": False, "reason": "NOTIONAL_INVALID"}
    if not all(math.isfinite(value) for value in (raw, rounded, minimum)) or min(raw, rounded, minimum) < 0 or minimum <= 0:
        return {"status": "UNMEASURABLE", "accepted": False, "reason": "NOTIONAL_INVALID"}
    return {"status": "PROVEN", "accepted": rounded >= minimum, "raw_notional_usdc": raw, "rounded_notional_usdc": rounded, "reason": "OK" if rounded >= minimum else "BELOW_MIN_NOTIONAL", "paper_read_only": True}


def tick_aligned_price_receipt(*, price: object, tick_size: object) -> dict[str, object]:
    """Require an execution price to be exactly representable on the observed tick grid."""

    try:
        value, tick = float(price), float(tick_size)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "aligned": False, "reason": "TICK_INPUT_INVALID"}
    if not all(math.isfinite(item) for item in (value, tick)) or value <= 0 or tick <= 0:
        return {"status": "UNMEASURABLE", "aligned": False, "reason": "TICK_INPUT_INVALID"}
    quotient = value / tick
    aligned = math.isclose(quotient, round(quotient), rel_tol=0.0, abs_tol=1e-10)
    return {"status": "PROVEN", "aligned": aligned, "price": value, "tick_size": tick, "reason": "OK" if aligned else "TICK_SIZE_VIOLATION", "paper_read_only": True}


def crossed_book_receipt(*, bid: object, ask: object) -> dict[str, object]:
    """Reject crossed or locked books before any paper execution or PnL."""

    try:
        bid_value, ask_value = float(bid), float(ask)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "valid": False, "reason": "BOOK_INPUT_INVALID"}
    if not all(math.isfinite(item) and item > 0 for item in (bid_value, ask_value)):
        return {"status": "UNMEASURABLE", "valid": False, "reason": "BOOK_INPUT_INVALID"}
    valid = bid_value < ask_value
    return {"status": "PROVEN", "valid": valid, "reason": "OK" if valid else "CROSSED_OR_LOCKED_BOOK", "paper_read_only": True}


def market_status_receipt(*, status: object) -> dict[str, object]:
    """Allow paper execution only for an explicit active market state."""

    normalized = str(status or "").casefold()
    active = normalized in {"active", "trading", "open"}
    return {"status": "PROVEN" if normalized else "UNMEASURABLE", "market_active": active, "reason": "OK" if active else "MARKET_NOT_ACTIVE", "paper_read_only": True}


def replay_fill_dedup_receipt(*, fill_ids: object) -> dict[str, object]:
    """Count each native fill once when replaying a paper ledger."""

    if not isinstance(fill_ids, (list, tuple)) or not fill_ids:
        return {"status": "UNMEASURABLE", "unique_fill_count": 0, "reason": "FILL_IDS_MISSING"}
    normalized = [str(value).strip() for value in fill_ids]
    if any(not value for value in normalized):
        return {"status": "UNMEASURABLE", "unique_fill_count": 0, "reason": "FILL_ID_INVALID"}
    unique = list(dict.fromkeys(normalized))
    return {"status": "PROVEN", "unique_fill_count": len(unique), "duplicate_count": len(normalized) - len(unique), "unique_fill_ids": unique, "paper_read_only": True}


def visible_capacity_receipt(*, requested_notional_usdc: object, visible_levels: object) -> dict[str, object]:
    """Expose insufficient visible capacity instead of silently filling invisible volume."""

    try:
        requested = float(requested_notional_usdc)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "fully_visible": False, "reason": "NOTIONAL_INVALID"}
    if not math.isfinite(requested) or requested <= 0 or not isinstance(visible_levels, (list, tuple)):
        return {"status": "UNMEASURABLE", "fully_visible": False, "reason": "CAPACITY_INPUT_INVALID"}
    capacity = 0.0
    for level in visible_levels:
        part = _level_parts(level)
        if part is not None:
            capacity += part[0] * part[1]
    return {"status": "PROVEN", "visible_capacity_usdc": capacity, "fully_visible": capacity + 1e-12 >= requested, "remaining_invisible_usdc": max(0.0, requested - capacity), "paper_read_only": True}


def market_impact_receipt(*, order_notional_usdc: object, visible_depth_usdc: object, base_impact_bps: object = 1.0) -> dict[str, object]:
    """Apply a monotone paper impact estimate only when visible depth is known."""

    try:
        order, depth, base = float(order_notional_usdc), float(visible_depth_usdc), float(base_impact_bps)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "reason": "IMPACT_INPUT_INVALID"}
    if not all(math.isfinite(value) for value in (order, depth, base)) or order <= 0 or depth <= 0 or base < 0:
        return {"status": "UNMEASURABLE", "reason": "IMPACT_INPUT_INVALID"}
    return {"status": "PROVEN", "impact_bps": base * (order / depth), "paper_read_only": True}


def maker_queue_fill_receipt(*, touched: object, queue_ahead_usdc: object, consumed_usdc: object, order_notional_usdc: object) -> dict[str, object]:
    """A maker touch fills only after observed queue ahead is consumed."""

    if not isinstance(touched, bool):
        return {"status": "UNMEASURABLE", "filled": False, "reason": "TOUCH_INVALID"}
    try:
        queue, consumed, order = float(queue_ahead_usdc), float(consumed_usdc), float(order_notional_usdc)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "filled": False, "reason": "QUEUE_INPUT_INVALID"}
    if not all(math.isfinite(value) for value in (queue, consumed, order)) or min(queue, consumed) < 0 or order <= 0:
        return {"status": "UNMEASURABLE", "filled": False, "reason": "QUEUE_INPUT_INVALID"}
    available = max(0.0, consumed - queue) if touched else 0.0
    filled = min(order, available)
    return {"status": "PROVEN", "filled": filled > 0, "filled_notional_usdc": filled, "partial": 0 < filled < order}


def liquidity_allocation_receipt(*, requests: list[dict[str, object]], available_notional_usdc: object) -> dict[str, object]:
    """Allocate one observed liquidity budget once per native signal id."""

    try:
        available = float(available_notional_usdc)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "allocations": {}}
    if not math.isfinite(available) or available < 0:
        return {"status": "UNMEASURABLE", "allocations": {}}
    allocations: dict[str, float] = {}
    for request in requests:
        signal_id = str(request.get("signal_id") or "").strip()
        if not signal_id or signal_id in allocations:
            continue
        try:
            requested = float(request.get("notional_usdc"))
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(requested) or requested <= 0:
            continue
        filled = min(requested, available)
        allocations[signal_id] = filled
        available -= filled
    return {"status": "PROVEN", "allocations": allocations, "remaining_notional_usdc": available, "paper_read_only": True}


def limit_order_priority_receipt(
    *,
    original_price: object,
    modified_price: object,
    original_ts_ms: object,
    modified_ts_ms: object,
) -> dict[str, object]:
    """A maker modification resets queue priority when price or order time changes."""

    try:
        original, modified = float(original_price), float(modified_price)
        original_ts, modified_ts = float(original_ts_ms), float(modified_ts_ms)
    except (TypeError, ValueError, OverflowError):
        return {"status": "UNMEASURABLE", "queue_reset": False, "reason": "PRIORITY_INPUT_INVALID"}
    values = (original, modified, original_ts, modified_ts)
    if not all(math.isfinite(value) for value in values) or min(original, modified, original_ts, modified_ts) < 0:
        return {"status": "UNMEASURABLE", "queue_reset": False, "reason": "PRIORITY_INPUT_INVALID"}
    reset = original != modified or modified_ts > original_ts
    return {
        "status": "PROVEN",
        "queue_reset": reset,
        "maker_priority": "RESET" if reset else "PRESERVED",
        "paper_read_only": True,
    }
