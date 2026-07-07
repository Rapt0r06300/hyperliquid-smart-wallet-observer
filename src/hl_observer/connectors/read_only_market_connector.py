"""In-memory read-only market connector for tests and local simulation glue."""

from __future__ import annotations

from dataclasses import dataclass

from .connector_base import ConnectorStatus


@dataclass(slots=True)
class InMemoryReadOnlyMarketConnector:
    name: str
    mids: dict[str, float]
    books: dict[str, dict[str, float]]

    def status(self) -> ConnectorStatus:
        return ConnectorStatus(name=self.name, read_only=True, healthy=True, detail=f"{len(self.mids)} mids")

    def mid(self, coin: str) -> float | None:
        return self.mids.get(str(coin).upper())

    def book(self, coin: str) -> dict[str, float] | None:
        book = self.books.get(str(coin).upper())
        return dict(book) if book else None


__all__ = ["InMemoryReadOnlyMarketConnector"]
