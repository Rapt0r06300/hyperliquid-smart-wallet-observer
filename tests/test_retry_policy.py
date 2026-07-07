from __future__ import annotations

import pytest

from hl_observer.core.retry import RetryExhausted, RetryPolicy, retry_sync


def test_retry_sync_retries_with_backoff():
    attempts = {"count": 0}
    sleeps: list[float] = []

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise TimeoutError("temporary")
        return "ok"

    result = retry_sync(
        flaky,
        policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.5, multiplier=2.0),
        sleep=sleeps.append,
    )

    assert result == "ok"
    assert sleeps == [0.5, 1.0]


def test_retry_sync_raises_when_exhausted():
    with pytest.raises(RetryExhausted):
        retry_sync(
            lambda: (_ for _ in ()).throw(ConnectionError("down")),
            policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.0),
            sleep=lambda _: None,
        )
