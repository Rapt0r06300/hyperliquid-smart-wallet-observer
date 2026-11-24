from __future__ import annotations

from tools.run_bounded_collector import _next_restart_backoff


def test_restart_backoff_is_zero_after_success() -> None:
    assert _next_restart_backoff(16.0, 0) == 0.0


def test_restart_backoff_grows_after_failure_and_is_capped() -> None:
    assert _next_restart_backoff(0.0, 1) == 1.0
    assert _next_restart_backoff(1.0, 1) == 2.0
    assert _next_restart_backoff(60.0, 1) == 60.0


def test_restart_backoff_never_uses_negative_limits() -> None:
    assert _next_restart_backoff(0.0, 1, initial_s=-2.0, maximum_s=0.0) == 0.0
