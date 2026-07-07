from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, TypeVar

T = TypeVar("T")


class RetryExhausted(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.25
    multiplier: float = 2.0
    max_delay_seconds: float = 5.0
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,)

    def delay_for_attempt(self, attempt_index: int) -> float:
        raw = self.base_delay_seconds * (self.multiplier ** max(0, attempt_index - 1))
        return min(self.max_delay_seconds, raw)


def retry_sync(
    fn: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
    on_error: Callable[[BaseException, int, float], None] | None = None,
) -> T:
    cfg = policy or RetryPolicy()
    last_error: BaseException | None = None
    for attempt in range(1, cfg.max_attempts + 1):
        try:
            return fn()
        except cfg.retry_exceptions as exc:
            last_error = exc
            if attempt >= cfg.max_attempts:
                break
            delay = cfg.delay_for_attempt(attempt)
            if on_error:
                on_error(exc, attempt, delay)
            sleep(delay)
    raise RetryExhausted(f"retry exhausted after {cfg.max_attempts} attempts") from last_error


__all__ = ["RetryExhausted", "RetryPolicy", "retry_sync"]
