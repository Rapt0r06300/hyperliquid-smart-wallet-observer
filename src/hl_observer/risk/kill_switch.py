from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class KillSwitch:
    active: bool = False
    reason: str | None = None

    def allows_trading(self) -> bool:
        return not self.active
