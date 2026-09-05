from __future__ import annotations

from hl_observer.core.retry import RetryPolicy, retry_sync
from hl_observer.market.classification import MID, classify_market


def test_retry_sync_reports_retry_to_on_error_callback() -> None:
    attempts = 0
    observed: list[tuple[type[BaseException], int, float]] = []

    def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TimeoutError("temporary")
        return "ok"

    result = retry_sync(
        flaky,
        policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.25),
        sleep=lambda _delay: None,
        on_error=lambda exc, attempt, delay: observed.append((type(exc), attempt, delay)),
    )

    assert result == "ok"
    assert observed == [(TimeoutError, 1, 0.25)]


def test_classify_market_returns_mid_for_mid_depth_and_volume() -> None:
    assert classify_market(l2_depth_usdt=40_000, daily_volume_usdt=2_000_000) == MID
