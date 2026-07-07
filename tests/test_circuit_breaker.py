from __future__ import annotations

import pytest

from hl_observer.core.circuit_breaker import CircuitBreaker, CircuitBreakerOpen


def test_circuit_breaker_opens_after_failures_and_half_opens():
    now = 0.0

    def clock() -> float:
        return now

    breaker = CircuitBreaker("ws", failure_threshold=2, recovery_timeout_seconds=10, clock=clock)
    breaker.record_failure()
    assert breaker.state == "CLOSED"
    breaker.record_failure()
    assert breaker.state == "OPEN"
    assert not breaker.allow_request()

    now = 11.0
    assert breaker.allow_request()
    assert breaker.state == "HALF_OPEN"
    breaker.record_success()
    assert breaker.state == "CLOSED"


def test_circuit_breaker_call_blocks_when_open():
    breaker = CircuitBreaker("rest", failure_threshold=1, recovery_timeout_seconds=100, clock=lambda: 0.0)
    breaker.record_failure()

    with pytest.raises(CircuitBreakerOpen):
        breaker.call(lambda: "never")
