from __future__ import annotations

import signal
import time

import pytest

from hl_observer.config import Settings
from tests.coverage_contract_harness import (
    _contains_while_loop,
    _invoke,
    _loop_has_explicit_safety_bound,
)


class _OuterDeadline(BaseException):
    pass


def _settings(tmp_path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'timeout.sqlite3'}",
        logs_dir=str(tmp_path / "logs"),
    )


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="POSIX timers required")
def test_invoke_preserves_an_existing_outer_sigalrm_timer(tmp_path) -> None:
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def outer_handler(*_args) -> None:
        raise _OuterDeadline("outer timeout fired")

    signal.signal(signal.SIGALRM, outer_handler)
    signal.setitimer(signal.ITIMER_REAL, 1.0)
    try:
        assert _invoke(lambda: "ok", 0, tmp_path, _settings(tmp_path)) == "ok"
        remaining, interval = signal.getitimer(signal.ITIMER_REAL)
        assert signal.getsignal(signal.SIGALRM) is outer_handler
        assert 0.0 < remaining <= 1.0
        assert interval == 0.0
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        previous_remaining, previous_interval = previous_timer
        if previous_remaining > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_remaining, previous_interval)


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="POSIX timers required")
def test_outer_timeout_survives_when_target_swallows_internal_exception(tmp_path) -> None:
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def outer_handler(*_args) -> None:
        raise _OuterDeadline("outer timeout fired")

    def swallows_exception_forever() -> None:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                time.sleep(0.002)
            except Exception:
                continue

    signal.signal(signal.SIGALRM, outer_handler)
    signal.setitimer(signal.ITIMER_REAL, 0.03)
    started = time.monotonic()
    try:
        with pytest.raises(_OuterDeadline, match="outer timeout fired"):
            _invoke(swallows_exception_forever, 0, tmp_path, _settings(tmp_path))
        assert time.monotonic() - started < 0.5
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        previous_remaining, previous_interval = previous_timer
        if previous_remaining > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_remaining, previous_interval)


def test_defaulted_loop_safety_bound_is_forced_by_synthetic_invoke(tmp_path) -> None:
    seen: list[int | None] = []

    def bounded_loop(*, max_ticks: int | None = None) -> int | None:
        while True:
            seen.append(max_ticks)
            return max_ticks

    assert _contains_while_loop(bounded_loop)
    assert _loop_has_explicit_safety_bound(bounded_loop)
    assert _invoke(bounded_loop, 0, tmp_path, _settings(tmp_path)) == 1
    assert seen == [1]


def test_unbounded_while_loop_is_detected_without_fake_safety_parameter() -> None:
    def unbounded_loop() -> None:
        while True:
            return None

    assert _contains_while_loop(unbounded_loop)
    assert not _loop_has_explicit_safety_bound(unbounded_loop)
