"""Connector base contracts for read-only market data and paper execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ConnectorStatus:
    name: str
    read_only: bool
    healthy: bool
    detail: str = ""


class ReadOnlyConnector(Protocol):
    name: str

    def status(self) -> ConnectorStatus:
        ...


__all__ = ["ConnectorStatus", "ReadOnlyConnector"]
