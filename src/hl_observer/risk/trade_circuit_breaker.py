"""Trading circuit breaker + depth guard (S7 — V9, Harrier A4).

Distinct from ``collection.circuit_breaker`` (which protects proxies/HTTP).
This one halts *paper* entries after N large trades inside a rolling window,
and exposes a depth guard to validate book liquidity before each decision.

Deterministic: callers inject the clock (``now_ms``) so behaviour is testable.

SAFETY: a trip blocks new paper entries; it never touches anything real.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CircuitBreakerConfig:
    max_trades: int = 3
    window_ms: int = 60_000
    big_trade_usdc: float = 1_000.0


class TradeCircuitBreaker:
    """Rolling-window breaker over *big* paper trades."""

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._cfg = config or CircuitBreakerConfig()
        self._events: deque[int] = deque()

    def record_trade(self, *, notional_usdc: float, now_ms: int) -> None:
        if notional_usdc >= self._cfg.big_trade_usdc:
            self._events.append(now_ms)
            self._prune(now_ms)

    def _prune(self, now_ms: int) -> None:
        cutoff = now_ms - self._cfg.window_ms
        while self._events and self._events[0] < cutoff:
            self._events.popleft()

    def is_tripped(self, now_ms: int) -> bool:
        self._prune(now_ms)
        return len(self._events) >= self._cfg.max_trades

    @property
    def count(self) -> int:
        return len(self._events)


def depth_guard(depth_usdc: float | None, *, min_depth_usdc: float = 200.0) -> bool:
    """True only when measured depth clears the minimum (None -> blocked)."""
    if depth_usdc is None:
        return False
    return depth_usdc >= min_depth_usdc
