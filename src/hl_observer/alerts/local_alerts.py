"""Local alerts (V12, repo 07): OFF by default; local-only, never an external action."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class LocalAlerts:
    enabled: bool = False                 # OFF by default
    _fired: list[dict] = field(default_factory=list)

    def raise_alert(self, *, kind: str, message: str, now_ms: int | None = None) -> dict | None:
        if not self.enabled:
            return None                   # disabled -> nothing happens
        a = {"kind": str(kind), "message": str(message),
             "at_ms": None if now_ms is None else int(now_ms), "external_action": False}
        self._fired.append(a)
        return a

    def fired(self) -> list[dict]:
        return list(self._fired)


__all__ = ["LocalAlerts"]
