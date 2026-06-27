"""V14 #176 — Rate-limit semaphore (25 req / 10 s) + REST weight budget (Harrier).

Pure, stateless evaluators the scan loop can consult before firing a REST request, plus a
tiny in-memory helper. No network; nothing here performs a request. read-only / paper-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass(frozen=True, slots=True)
class RateLimitConfig:
    max_requests: int = 25
    window_s: float = 10.0
    max_weight_per_window: int = 1_200   # REST weight budget per window


@dataclass(frozen=True, slots=True)
class RateLimitVerdict:
    allowed: bool
    used: int
    remaining: int
    retry_after_s: float
    reason: str


def evaluate_rate_limit(
    recent_request_times_s: Sequence[float],
    *,
    now_s: float,
    config: RateLimitConfig | None = None,
) -> RateLimitVerdict:
    """Sliding-window check: count requests within the last `window_s`."""
    cfg = config or RateLimitConfig()
    window_start = float(now_s) - cfg.window_s
    in_window = sorted(t for t in recent_request_times_s if t > window_start)
    used = len(in_window)
    remaining = max(0, cfg.max_requests - used)
    if used >= cfg.max_requests:
        # next slot frees when the oldest in-window request exits the window
        retry = max(0.0, in_window[0] + cfg.window_s - float(now_s))
        return RateLimitVerdict(False, used, 0, round(retry, 4), "RATE_LIMITED")
    return RateLimitVerdict(True, used, remaining, 0.0, "OK")


def weight_budget_check(*, used_weight: int, request_weight: int, max_weight: int) -> tuple[bool, int]:
    """True + remaining when the request fits the REST weight budget for this window."""
    remaining = int(max_weight) - int(used_weight)
    return (int(request_weight) <= remaining, max(0, remaining - int(request_weight)))


class RateLimiterState:
    """Minimal in-memory helper (optional). Pure logic delegates to evaluate_rate_limit."""

    def __init__(self, config: RateLimitConfig | None = None) -> None:
        self.config = config or RateLimitConfig()
        self._times: list[float] = []

    def try_acquire(self, now_s: float) -> RateLimitVerdict:
        self._times = [t for t in self._times if t > now_s - self.config.window_s]
        verdict = evaluate_rate_limit(self._times, now_s=now_s, config=self.config)
        if verdict.allowed:
            self._times.append(float(now_s))
        return verdict


__all__ = [
    "RateLimitConfig",
    "RateLimitVerdict",
    "evaluate_rate_limit",
    "weight_budget_check",
    "RateLimiterState",
]
