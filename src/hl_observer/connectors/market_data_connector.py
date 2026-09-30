"""Market data connector facade, read-only."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MarketQuote:
    coin: str
    bid: float
    ask: float
    source: str

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


class StaticMarketDataConnector:
    def __init__(self, quotes: dict[str, MarketQuote]) -> None:
        self.quotes = {coin.upper(): quote for coin, quote in quotes.items()}

    def quote(self, coin: str) -> MarketQuote | None:
        return self.quotes.get(str(coin).upper())


__all__ = ["MarketQuote", "StaticMarketDataConnector"]
