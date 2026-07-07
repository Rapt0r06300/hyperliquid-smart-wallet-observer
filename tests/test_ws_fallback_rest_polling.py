"""Phase 10 (canonical): when the WS heartbeat goes stale, the runtime must fall
back to bounded REST polling; stale wallet state is a no-trade, not a guess."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hyper_smart_observer.realtime_monitor.freshness_guard import LivePositionFreshnessGuard
from hyper_smart_observer.realtime_monitor.heartbeat import heartbeat_stale

W = "0x" + "e" * 40


def test_heartbeat_stale_triggers_rest_fallback():
    fresh = datetime.now(timezone.utc) - timedelta(seconds=2)
    old = datetime.now(timezone.utc) - timedelta(seconds=120)
    assert heartbeat_stale(fresh, max_age_seconds=30) is False
    assert heartbeat_stale(old, max_age_seconds=30) is True       # -> REST reconcile
    assert heartbeat_stale(None, max_age_seconds=30) is True       # never seen -> REST


def test_stale_or_missing_wallet_state_is_no_trade():
    guard = LivePositionFreshnessGuard(max_age_seconds=20)
    # never seen -> SOURCE_UNAVAILABLE no-trade
    d_missing = guard.evaluate(W)
    assert d_missing.allowed is False and d_missing.no_trade is not None
    # stale by 100s -> STALE_SIGNAL no-trade
    guard.update(W, position_at=datetime.now(timezone.utc) - timedelta(seconds=100))
    d_stale = guard.evaluate(W)
    assert d_stale.allowed is False
    assert d_stale.reason == "STALE_WALLET_STATE"
