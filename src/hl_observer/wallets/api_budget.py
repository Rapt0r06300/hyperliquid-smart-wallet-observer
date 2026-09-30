"""SCALE — Budget API global (token bucket + poids HL) → zéro 429 en régime.

Hyperliquid pondère les requêtes REST: poids = 1 + floor(batch/40), et les
endpoints type userFills ajoutent un poids par 20 items renvoyés. Sans budget
partagé, plusieurs scanners se marchent dessus et déclenchent des 429. Ce module
tient un token bucket global et refuse/temporise AVANT de taper le mur. Pur,
déterministe (l'horloge est injectée), aucune I/O réseau ici.
"""

from __future__ import annotations

import threading


def hl_request_weight(*, batch_len: int = 0, items_returned: int = 0, per_items: int = 20) -> int:
    """Poids d'une requête HL: 1 + floor(batch/40) + floor(items/20) pour les listes."""
    w = 1 + (int(batch_len) // 40)
    if items_returned:
        w += int(items_returned) // int(per_items)
    return max(1, w)


class ApiBudget:
    """Token bucket: capacité 'capacity' poids, réapprovisionné 'refill_per_sec'."""

    def __init__(self, capacity: float = 1200.0, refill_per_sec: float = 100.0) -> None:
        self.capacity = float(capacity)
        self.refill = float(refill_per_sec)
        self._tokens = float(capacity)
        self._last_ms = None
        self._lock = threading.Lock()
        self._granted = 0
        self._denied = 0

    def _refill_to(self, now_ms: int) -> None:
        if self._last_ms is None:
            self._last_ms = int(now_ms)
            return
        dt = max(0.0, (int(now_ms) - self._last_ms) / 1000.0)
        self._tokens = min(self.capacity, self._tokens + dt * self.refill)
        self._last_ms = int(now_ms)

    def try_consume(self, weight: int, now_ms: int) -> bool:
        with self._lock:
            self._refill_to(now_ms)
            if self._tokens >= weight:
                self._tokens -= weight
                self._granted += 1
                return True
            self._denied += 1
            return False

    def wait_ms_for(self, weight: int, now_ms: int) -> float:
        """Combien de ms attendre avant de pouvoir consommer 'weight' (backoff)."""
        with self._lock:
            self._refill_to(now_ms)
            if self._tokens >= weight:
                return 0.0
            missing = weight - self._tokens
            return round(missing / self.refill * 1000.0, 1) if self.refill > 0 else float("inf")

    def observe_user_rate_limit(self, remaining: float, capacity: float | None = None) -> None:
        """Aligne le bucket sur le vrai budget renvoyé par l'endpoint userRateLimit."""
        with self._lock:
            if capacity is not None and capacity > 0:
                self.capacity = float(capacity)
            self._tokens = max(0.0, min(self.capacity, float(remaining)))

    def stats(self) -> dict:
        with self._lock:
            total = self._granted + self._denied
            return {
                "tokens": round(self._tokens, 2),
                "capacity": self.capacity,
                "granted": self._granted,
                "denied": self._denied,
                "deny_ratio": round(self._denied / total, 4) if total else 0.0,
            }


__all__ = ["hl_request_weight", "ApiBudget"]
