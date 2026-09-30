from hyper_smart_observer.hyperliquid_client.rate_limiter import LocalRateLimiter


def test_rate_limiter_waits_between_requests():
    times = iter([0.0, 0.1, 0.25])
    sleeps = []

    limiter = LocalRateLimiter(
        250,
        clock=lambda: next(times),
        sleeper=lambda seconds: sleeps.append(seconds),
    )

    limiter.wait()
    limiter.wait()

    assert sleeps == [0.15]
