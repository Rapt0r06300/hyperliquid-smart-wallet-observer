from hl_observer.risk.circuit_breaker import CircuitBreaker, CircuitBreakerConfig, TradeOutcome


def test_record_during_active_cooldown_stays_blocked_after_triggering_trades_age_out() -> None:
    cfg = CircuitBreakerConfig(
        max_trades_in_window=1,
        max_consecutive_losses=99,
        max_big_losses_in_window=99,
        window_sec=10.0,
        cooldown_sec=100.0,
    )
    cb = CircuitBreaker(cfg)

    assert cb.record(TradeOutcome(timestamp_sec=0.0, pnl_usdc=1.0)).entry_allowed
    trip = cb.record(TradeOutcome(timestamp_sec=1.0, pnl_usdc=1.0))
    assert "TRADE_RATE_TOO_HIGH" in trip.reasons

    during = cb.record(TradeOutcome(timestamp_sec=20.0, pnl_usdc=1.0))

    assert during.tripped
    assert during.reasons == ("COOLDOWN_ACTIVE",)
    assert during.cooldown_until_sec == 101.0
    assert during.trades_in_window == 1
