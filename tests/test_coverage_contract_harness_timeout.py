from __future__ import annotations

import signal

import pytest

from hl_observer.config import Settings
from tests.coverage_contract_harness import _invoke


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="POSIX timers required")
def test_invoke_preserves_an_existing_outer_sigalrm_timer(tmp_path) -> None:
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)

    def outer_handler(*_args) -> None:
        raise TimeoutError("outer timeout fired")

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'timeout.sqlite3'}",
        logs_dir=str(tmp_path / "logs"),
    )
    signal.signal(signal.SIGALRM, outer_handler)
    signal.setitimer(signal.ITIMER_REAL, 1.0)
    try:
        assert _invoke(lambda: "ok", 0, tmp_path, settings) == "ok"
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
