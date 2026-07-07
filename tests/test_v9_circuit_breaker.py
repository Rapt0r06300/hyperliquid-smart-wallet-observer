import pytest

from hl_observer.risk.circuit_breaker import (
    BreakerDecision,
    CircuitBreaker,
    CircuitBreakerConfig,
    TradeOutcome,
)


def _loss(ts, amt=1.0):
    return TradeOutcome(timestamp_sec=ts, pnl_usdc=-abs(amt), notional_usdc=50.0)


def _win(ts, amt=1.0):
    return TradeOutcome(timestamp_sec=ts, pnl_usdc=abs(amt), notional_usdc=50.0)


def test_no_trip_under_normal_conditions():
    cb = CircuitBreaker(CircuitBreakerConfig(max_trades_in_window=12, window_sec=300))
    d = cb.record(_win(10))
    assert isinstance(d, BreakerDecision)
    assert d.entry_allowed
    assert not d.tripped
    assert cb.allow_entry(11)


def test_trip_on_trade_rate_burst():
    cfg = CircuitBreakerConfig(max_trades_in_window=5, window_sec=60, cooldown_sec=100)
    cb = CircuitBreaker(cfg)
    last = None
    for i in range(6):  # 6 > 5 within the 60s window
        last = cb.record(_win(float(i)))
    assert last.tripped
    assert "TRADE_RATE_TOO_HIGH" in last.reasons
    assert not cb.allow_entry(6.0)


def test_trip_on_consecutive_losses():
    cfg = CircuitBreakerConfig(max_consecutive_losses=4, window_sec=10_000, cooldown_sec=50)
    cb = CircuitBreaker(cfg)
    for i in range(3):
        assert cb.record(_loss(float(i))).entry_allowed
    d = cb.record(_loss(3.0))  # 4th consecutive loss
    assert d.tripped
    assert "CONSECUTIVE_LOSSES" in d.reasons
    assert d.consecutive_losses == 4


def test_win_resets_consecutive_loss_streak():
    cfg = CircuitBreakerConfig(max_consecutive_losses=3, window_sec=10_000, cooldown_sec=0)
    cb = CircuitBreaker(cfg)
    cb.record(_loss(0))
    cb.record(_loss(1))
    cb.record(_win(2))  # streak reset
    d = cb.record(_loss(3))
    assert not d.tripped
    assert d.consecutive_losses == 1


def test_trip_on_big_loss_cluster():
    cfg = CircuitBreakerConfig(
        big_loss_usdc=5.0,
        max_big_losses_in_window=3,
        max_consecutive_losses=99,
        max_trades_in_window=999,
        window_sec=300,
        cooldown_sec=120,
    )
    cb = CircuitBreaker(cfg)
    cb.record(_loss(0, amt=6))
    cb.record(_loss(1, amt=7))
    d = cb.record(_loss(2, amt=8))  # 3rd big loss
    assert d.tripped
    assert "BIG_LOSS_CLUSTER" in d.reasons
    assert d.big_losses_in_window == 3


def test_small_losses_do_not_count_as_big():
    cfg = CircuitBreakerConfig(big_loss_usdc=5.0, max_big_losses_in_window=2,
                               max_consecutive_losses=99, max_trades_in_window=999)
    cb = CircuitBreaker(cfg)
    cb.record(_loss(0, amt=1))
    d = cb.record(_loss(1, amt=2))
    assert not d.tripped
    assert d.big_losses_in_window == 0


def test_cooldown_blocks_then_recovers():
    cfg = CircuitBreakerConfig(max_consecutive_losses=2, window_sec=10_000, cooldown_sec=600)
    cb = CircuitBreaker(cfg)
    cb.record(_loss(0))
    d = cb.record(_loss(1))  # trip at t=1
    assert d.tripped
    assert d.cooldown_until_sec == pytest.approx(601.0)
    # still cooling at t=300
    assert not cb.allow_entry(300.0)
    # cooldown elapsed at t=602 (old trades also aged out of window)
    assert cb.allow_entry(602.0)


def test_window_prunes_old_trades():
    cfg = CircuitBreakerConfig(max_trades_in_window=3, window_sec=100, cooldown_sec=0)
    cb = CircuitBreaker(cfg)
    for i in range(4):
        cb.record(_win(float(i)))  # 4 trades close together -> would trip
    # far in the future, all old trades drop out of the window
    d = cb.evaluate(1_000.0)
    assert d.trades_in_window == 0
    assert d.entry_allowed


def test_reset_clears_state():
    cb = CircuitBreaker(CircuitBreakerConfig(max_consecutive_losses=1, cooldown_sec=999))
    cb.record(_loss(0))
    assert not cb.allow_entry(1)
    cb.reset()
    assert cb.allow_entry(1)


def test_config_validation():
    with pytest.raises(ValueError):
        CircuitBreakerConfig(window_sec=0)
    with pytest.raises(ValueError):
        CircuitBreakerConfig(cooldown_sec=-1)


def test_breaker_never_places_orders_pure_paper():
    # The breaker exposes only evaluation/state methods — no execution surface.
    cb = CircuitBreaker()
    public = {n for n in dir(cb) if not n.startswith("_")}
    for forbidden in ("submit", "place", "order", "sign", "send", "execute"):
        assert not any(forbidden in name.lower() for name in public)
