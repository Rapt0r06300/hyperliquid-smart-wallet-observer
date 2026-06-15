from datetime import datetime, timedelta
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc

from hyper_smart_observer.copy_mode.copy_models import NoTradeReason
from hyper_smart_observer.realtime_monitor.freshness_guard import LivePositionFreshnessGuard


GOOD_ADDRESS = "0x" + "f" * 40


def test_freshness_guard_allows_recent_position_update():
    now = datetime.now(UTC)
    guard = LivePositionFreshnessGuard(max_age_seconds=20)
    guard.update(GOOD_ADDRESS, position_at=now - timedelta(seconds=5))

    decision = guard.evaluate(GOOD_ADDRESS, now=now)

    assert decision.allowed
    assert decision.reason == "FRESH_WALLET_STATE"
    assert decision.age_seconds is not None and decision.age_seconds <= 5


def test_freshness_guard_rejects_stale_position_update_as_no_trade():
    now = datetime.now(UTC)
    guard = LivePositionFreshnessGuard(max_age_seconds=20)
    guard.update(GOOD_ADDRESS, fill_at=now - timedelta(seconds=40))

    decision = guard.evaluate(GOOD_ADDRESS, now=now)

    assert not decision.allowed
    assert decision.reason == "STALE_WALLET_STATE"
    assert decision.no_trade is not None
    assert decision.no_trade.reason == NoTradeReason.STALE_SIGNAL


def test_freshness_guard_rejects_missing_wallet_state():
    guard = LivePositionFreshnessGuard(max_age_seconds=20)

    decision = guard.evaluate(GOOD_ADDRESS)

    assert not decision.allowed
    assert decision.reason == "NO_FRESH_WALLET_STATE"
    assert decision.no_trade is not None
    assert decision.no_trade.reason == NoTradeReason.SOURCE_UNAVAILABLE
