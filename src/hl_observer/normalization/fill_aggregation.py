"""Aggregate fills that belong to the same leader action."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import math
from typing import Iterable

from hl_observer.instrument_identity import preserve_native_instrument_symbol


@dataclass(frozen=True, slots=True)
class AggregatedFill:
    wallet: str
    coin: str
    direction: str
    oid: str
    total_size: float
    notional_usdt: float
    first_time_ms: int
    last_time_ms: int
    fill_refs: tuple[str, ...]


def _finite_positive_float(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not parsed.is_finite() or parsed <= 0:
        return None
    result = float(parsed)
    return result if math.isfinite(result) and result > 0 else None


def _exact_positive_int(value: object) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not parsed.is_finite() or parsed != parsed.to_integral_value() or parsed <= 0:
        return None
    return int(parsed)


def aggregate_fills_by_oid(fills: Iterable[dict[str, object]]) -> tuple[AggregatedFill, ...]:
    groups: dict[tuple[str, str, str, str], list[dict[str, object]]] = {}
    for fill in fills:
        wallet = str(fill.get("wallet") or fill.get("user") or "").lower()
        coin = preserve_native_instrument_symbol(fill.get("coin"))
        direction = str(fill.get("dir") or fill.get("direction") or fill.get("side") or "").strip()
        oid = str(fill.get("oid") or fill.get("hash") or fill.get("tid") or "")
        if not wallet or not coin or not oid:
            continue
        groups.setdefault((wallet, coin, direction, oid), []).append(fill)
    rows: list[AggregatedFill] = []
    for (wallet, coin, direction, oid), items in groups.items():
        parsed_items: list[tuple[float, float, int]] = []
        for item in items:
            size = _finite_positive_float(item.get("sz") if item.get("sz") is not None else item.get("size"))
            price = _finite_positive_float(item.get("px") if item.get("px") is not None else item.get("price"))
            timestamp = _exact_positive_int(item.get("time") if item.get("time") is not None else item.get("time_ms"))
            if size is None or price is None or timestamp is None:
                parsed_items = []
                break
            parsed_items.append((size, price, timestamp))
        if not parsed_items:
            continue
        total_size = sum(size for size, _, _ in parsed_items)
        notional = sum(size * price for size, price, _ in parsed_items)
        times = [timestamp for _, _, timestamp in parsed_items]
        refs = tuple(str(item.get("hash") or item.get("tid") or item.get("oid") or "") for item in items)
        rows.append(
            AggregatedFill(
                wallet=wallet,
                coin=coin,
                direction=direction,
                oid=oid,
                total_size=round(total_size, 10),
                notional_usdt=round(notional, 8),
                first_time_ms=min(times) if times else 0,
                last_time_ms=max(times) if times else 0,
                fill_refs=tuple(ref for ref in refs if ref),
            )
        )
    return tuple(sorted(rows, key=lambda row: (row.wallet, row.coin, row.first_time_ms)))


__all__ = ["AggregatedFill", "aggregate_fills_by_oid"]
