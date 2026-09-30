from hl_observer.collection.backoff import BackoffPolicy, compute_backoff_delay
from hl_observer.collection.rate_limiter import WindowRateLimiter
from hl_observer.execution_core.canonical_order_candidate import creer_candidat


def test_rate_limit_backoff_uses_fail_slow_reason() -> None:
    decision = compute_backoff_delay(
        attempt=1,
        policy=BackoffPolicy(jitter_ratio=0.0),
        status_code=429,
        shard_key="public-info",
    )

    assert decision.reason == "RATE_LIMIT_OR_FORBIDDEN_BACKOFF"
    assert decision.delay_seconds == 0.5
    assert decision.retry_after_respected is False


def test_rate_limiter_remaining_reports_capacity_after_reservation() -> None:
    limiter = WindowRateLimiter(max_requests=2, window_seconds=10.0)

    assert limiter.reserve(100.0) == (True, 0.0)
    assert limiter.remaining(100.0) == 1


def test_canonical_order_candidate_rejects_missing_coin() -> None:
    candidate = creer_candidat(
        coin="",
        cote="BUY",
        quantite=1.0,
        prix=100.0,
        type_exec="TAKER",
        budget_disponible=1_000.0,
    )

    assert candidate["valide"] is False
    assert candidate["erreurs"] == ["COIN_MANQUANT"]
