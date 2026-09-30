"""Graceful shutdown state for local loops."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class GracefulShutdown:
    requested: bool = False
    reason: str = ""

    def request(self, reason: str = "USER_REQUEST") -> None:
        self.requested = True
        self.reason = str(reason)


__all__ = ["GracefulShutdown"]
