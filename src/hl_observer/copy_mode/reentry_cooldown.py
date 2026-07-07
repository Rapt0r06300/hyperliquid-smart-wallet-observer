"""B6 — Re-entry cooldown (anti-churn) : pas de rachat immédiat d'un coin après une sortie.

Distinct du FillCooldown (dédup de copies). Ici on empêche de ré-entrer sur un coin
pendant N secondes après un exit (evan-kolberg reentry_cooldown_seconds ~1800).
Read-only / paper.
"""

from __future__ import annotations


class ReentryCooldown:
    def __init__(self, cooldown_seconds: float = 1800.0) -> None:
        self.cooldown_seconds = float(cooldown_seconds)
        self._last_exit_ms: dict[str, int] = {}

    def record_exit(self, coin: str, ts_ms: int) -> None:
        self._last_exit_ms[str(coin)] = int(ts_ms)

    def can_reenter(self, coin: str, now_ms: int) -> bool:
        last = self._last_exit_ms.get(str(coin))
        if last is None:
            return True
        return (int(now_ms) - last) >= self.cooldown_seconds * 1000.0

    def seconds_remaining(self, coin: str, now_ms: int) -> float:
        last = self._last_exit_ms.get(str(coin))
        if last is None:
            return 0.0
        elapsed = (int(now_ms) - last) / 1000.0
        return max(0.0, self.cooldown_seconds - elapsed)


__all__ = ["ReentryCooldown"]
