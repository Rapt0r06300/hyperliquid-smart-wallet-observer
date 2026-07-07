"""Detect cross-source price discrepancies from read-only WS events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from hl_observer.realtime.multi_source_price_stream import PriceEvent


@dataclass(frozen=True, slots=True)
class PriceDiscrepancy:
    coin: str
    source_a: str
    source_b: str
    spread_bps: float
    decision: str


def detect_ws_price_discrepancies(events: Iterable[PriceEvent], *, min_spread_bps: float = 20.0) -> tuple[PriceDiscrepancy, ...]:
    by_coin: dict[str, list[PriceEvent]] = {}
    for event in events:
        by_coin.setdefault(event.coin.upper(), []).append(event)
    out: list[PriceDiscrepancy] = []
    for coin, rows in by_coin.items():
        for i, a in enumerate(rows):
            for b in rows[i + 1 :]:
                spread = abs(a.mid - b.mid) / max((a.mid + b.mid) / 2.0, 1e-9) * 10_000.0
                if spread >= min_spread_bps:
                    out.append(PriceDiscrepancy(coin, a.source, b.source, round(spread, 8), "PAPER_DISCREPANCY"))
    return tuple(out)


__all__ = ["PriceDiscrepancy", "detect_ws_price_discrepancies"]
