"""Aggregate fills that belong to the same leader action."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


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


def aggregate_fills_by_oid(fills: Iterable[dict[str, object]]) -> tuple[AggregatedFill, ...]:
    groups: dict[tuple[str, str, str, str], list[dict[str, object]]] = {}
    for fill in fills:
        wallet = str(fill.get("wallet") or fill.get("user") or "").lower()
        coin = str(fill.get("coin") or "").upper()
        direction = str(fill.get("dir") or fill.get("direction") or fill.get("side") or "").strip()
        oid = str(fill.get("oid") or fill.get("hash") or fill.get("tid") or "")
        if not wallet or not coin or not oid:
            continue
        groups.setdefault((wallet, coin, direction, oid), []).append(fill)
    rows: list[AggregatedFill] = []
    for (wallet, coin, direction, oid), items in groups.items():
        total_size = sum(abs(float(item.get("sz") or item.get("size") or 0.0)) for item in items)
        notional = sum(
            abs(float(item.get("sz") or item.get("size") or 0.0)) * abs(float(item.get("px") or item.get("price") or 0.0))
            for item in items
        )
        times = [int(item.get("time") or item.get("time_ms") or 0) for item in items]
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
