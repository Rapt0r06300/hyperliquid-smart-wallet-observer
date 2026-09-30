from __future__ import annotations

from dataclasses import dataclass


CIRCUIT_CLOSED = "CLOSED"
CIRCUIT_OPEN = "OPEN"
CIRCUIT_HALF_OPEN = "HALF_OPEN"


@dataclass(frozen=True, slots=True)
class CircuitBreakerConfig:
    failure_threshold: int = 3
    cooldown_seconds: float = 30.0


@dataclass(frozen=True, slots=True)
class CircuitBreakerState:
    name: str
    state: str = CIRCUIT_CLOSED
    failures: int = 0
    opened_at_seconds: float | None = None
    successes: int = 0


def can_attempt(state: CircuitBreakerState, *, now_seconds: float, config: CircuitBreakerConfig | None = None) -> bool:
    config = config or CircuitBreakerConfig()
    if state.state == CIRCUIT_CLOSED:
        return True
    if state.state == CIRCUIT_HALF_OPEN:
        return True
    if state.opened_at_seconds is None:
        return False
    return now_seconds - state.opened_at_seconds >= config.cooldown_seconds


def record_success(state: CircuitBreakerState) -> CircuitBreakerState:
    return CircuitBreakerState(
        name=state.name,
        state=CIRCUIT_CLOSED,
        failures=0,
        opened_at_seconds=None,
        successes=state.successes + 1,
    )


def record_failure(
    state: CircuitBreakerState,
    *,
    now_seconds: float,
    config: CircuitBreakerConfig | None = None,
) -> CircuitBreakerState:
    config = config or CircuitBreakerConfig()
    failures = state.failures + 1
    if failures >= max(1, config.failure_threshold):
        return CircuitBreakerState(
            name=state.name,
            state=CIRCUIT_OPEN,
            failures=failures,
            opened_at_seconds=now_seconds,
            successes=state.successes,
        )
    return CircuitBreakerState(
        name=state.name,
        state=state.state,
        failures=failures,
        opened_at_seconds=state.opened_at_seconds,
        successes=state.successes,
    )


def maybe_half_open(
    state: CircuitBreakerState,
    *,
    now_seconds: float,
    config: CircuitBreakerConfig | None = None,
) -> CircuitBreakerState:
    config = config or CircuitBreakerConfig()
    if state.state != CIRCUIT_OPEN or state.opened_at_seconds is None:
        return state
    if now_seconds - state.opened_at_seconds < config.cooldown_seconds:
        return state
    return CircuitBreakerState(
        name=state.name,
        state=CIRCUIT_HALF_OPEN,
        failures=state.failures,
        opened_at_seconds=state.opened_at_seconds,
        successes=state.successes,
    )
