"""Compare prices from multiple read-only sources."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CrossSourcePrice:
    source: str
    coin: str
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (float(self.bid) + float(self.ask)) / 2.0


@dataclass(frozen=True, slots=True)
class CrossSourceDiscrepancy:
    coin: str
    low_source: str
    high_source: str
    low_mid: float
    high_mid: float
    spread_bps: float


def compare_cross_source_prices(prices: list[CrossSourcePrice]) -> list[CrossSourceDiscrepancy]:
    by_coin: dict[str, list[CrossSourcePrice]] = {}
    for price in prices:
        if price.bid > 0 and price.ask > 0 and price.ask >= price.bid:
            by_coin.setdefault(price.coin.upper(), []).append(price)
    rows: list[CrossSourceDiscrepancy] = []
    for coin, values in by_coin.items():
        if len(values) < 2:
            continue
        low = min(values, key=lambda item: item.mid)
        high = max(values, key=lambda item: item.mid)
        if low.source == high.source or low.mid <= 0:
            continue
        spread = (high.mid / low.mid - 1.0) * 10_000.0
        rows.append(CrossSourceDiscrepancy(coin, low.source, high.source, round(low.mid, 10), round(high.mid, 10), round(spread, 8)))
    return sorted(rows, key=lambda row: row.spread_bps, reverse=True)


__all__ = ["CrossSourceDiscrepancy", "CrossSourcePrice", "compare_cross_source_prices"]
