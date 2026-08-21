from __future__ import annotations

import signal
import time

import pytest

from hl_observer.config import Settings
from tests.coverage_contract_harness import _invoke


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


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="POSIX timers required")
def test_hard_internal_timeout_crosses_except_exception(tmp_path) -> None:
    def swallows_soft_timeout() -> None:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                time.sleep(0.002)
            except Exception:
                continue

    started = time.monotonic()
    with pytest.raises(SystemExit, match="synthetic coverage call exceeded hard deadline"):
        _invoke(swallows_soft_timeout, 0, tmp_path, _settings(tmp_path))
    assert time.monotonic() - started < 0.5
