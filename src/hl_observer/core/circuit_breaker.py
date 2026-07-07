from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

T = TypeVar("T")


class CircuitBreakerOpen(RuntimeError):
    pass


@dataclass(slots=True)
class CircuitBreaker:
    name: str
    failure_threshold: int = 3
    recovery_timeout_seconds: float = 30.0
    clock: Callable[[], float] = time.monotonic
    state: str = "CLOSED"
    failure_count: int = 0
    last_failure_at: float | None = None
    history: list[dict[str, object]] = field(default_factory=list)

    def allow_request(self) -> bool:
        if self.state == "CLOSED":
            return True
        if self.state == "HALF_OPEN":
            return True
        if self.last_failure_at is None:
            return False
        if self.clock() - self.last_failure_at >= self.recovery_timeout_seconds:
            self.state = "HALF_OPEN"
            self.history.append({"event": "half_open", "at": self.clock()})
            return True
        return False

    def record_success(self) -> None:
        self.failure_count = 0
        self.state = "CLOSED"
        self.history.append({"event": "success", "at": self.clock()})

    def record_failure(self) -> None:
        self.failure_count += 1
        self.last_failure_at = self.clock()
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"
            self.history.append({"event": "open", "at": self.last_failure_at})
        else:
            self.history.append({"event": "failure", "at": self.last_failure_at})

    def call(self, fn: Callable[..., T], *args: object, **kwargs: object) -> T:
        if not self.allow_request():
            raise CircuitBreakerOpen(f"circuit breaker {self.name} is open")
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result


__all__ = ["CircuitBreaker", "CircuitBreakerOpen"]
