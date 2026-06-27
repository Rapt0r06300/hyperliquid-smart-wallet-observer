from hl_observer.collection.backoff import BackoffPolicy, compute_backoff_delay
from hl_observer.collection.circuit_breaker import (
    CIRCUIT_CLOSED,
    CIRCUIT_HALF_OPEN,
    CIRCUIT_OPEN,
    CircuitBreakerConfig,
    CircuitBreakerState,
    can_attempt,
    maybe_half_open,
    record_failure,
    record_success,
)
from hl_observer.collection.html_scraper import parse_wallets_from_html
from hl_observer.collection.rate_limiter import WindowRateLimiter


def test_backoff_respects_retry_after_header():
    decision = compute_backoff_delay(attempt=3, retry_after_seconds=7.5, status_code=429)

    assert decision.delay_seconds == 7.5
    assert decision.reason == "RETRY_AFTER"
    assert decision.retry_after_respected is True


def test_backoff_is_bounded_and_deterministic():
    policy = BackoffPolicy(base_seconds=1.0, max_seconds=4.0, jitter_ratio=0.0)
    first = compute_backoff_delay(attempt=5, policy=policy, status_code=500, shard_key="BTC")
    second = compute_backoff_delay(attempt=5, policy=policy, status_code=500, shard_key="BTC")

    assert first == second
    assert first.delay_seconds == 4.0
    assert first.reason == "SERVER_ERROR_BACKOFF"


def test_circuit_breaker_opens_then_half_opens_after_cooldown():
    config = CircuitBreakerConfig(failure_threshold=2, cooldown_seconds=10.0)
    state = CircuitBreakerState(name="egress-a")

    state = record_failure(state, now_seconds=1.0, config=config)
    assert state.state == CIRCUIT_CLOSED
    state = record_failure(state, now_seconds=2.0, config=config)
    assert state.state == CIRCUIT_OPEN
    assert can_attempt(state, now_seconds=5.0, config=config) is False
    state = maybe_half_open(state, now_seconds=13.0, config=config)
    assert state.state == CIRCUIT_HALF_OPEN
    assert can_attempt(state, now_seconds=13.0, config=config) is True
    state = record_success(state)
    assert state.state == CIRCUIT_CLOSED
    assert state.failures == 0


def test_window_rate_limiter_blocks_until_window_rolls():
    limiter = WindowRateLimiter(max_requests=3, window_seconds=10.0)

    assert limiter.reserve(0.0) == (True, 0.0)
    assert limiter.reserve(1.0) == (True, 0.0)
    assert limiter.reserve(2.0) == (True, 0.0)
    allowed, wait = limiter.reserve(3.0)
    assert allowed is False
    assert wait == 7.0
    assert limiter.reserve(10.1) == (True, 0.0)


def test_html_scraper_extracts_only_complete_wallets_and_rejects_truncated():
    html = """
    <html><body>
      <a href="/explorer/address/0x1111111111111111111111111111111111111111">leader</a>
      <span>0x2222...abcd</span>
      <div data-wallet="0xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"></div>
    </body></html>
    """

    result = parse_wallets_from_html(html, source_url="https://app.hyperliquid.xyz/explorer")

    assert result.read_only is True
    assert result.data_fabricated is False
    assert [item.address for item in result.candidates] == [
        "0x1111111111111111111111111111111111111111",
        "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ]
    assert result.truncated_rejected == ("0x2222...abcd",)
    assert "TRUNCATED_ADDRESS_REJECTED" in result.warnings


def test_html_scraper_empty_page_returns_empty_honest_state():
    result = parse_wallets_from_html("<html><body>No wallets here</body></html>", source_url="fixture://empty")

    assert result.candidates == ()
    assert result.data_fabricated is False
    assert "NO_FULL_WALLET_FOUND" in result.warnings
