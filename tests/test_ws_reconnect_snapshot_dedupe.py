"""Phase 10 (canonical): bounded reconnect backoff + snapshot/item dedupe so a
reconnect re-delivering a snapshot cannot create duplicate events."""

from __future__ import annotations

from hyper_smart_observer.realtime_monitor.dedupe import EventDedupe
from hyper_smart_observer.realtime_monitor.reconnect import backoff_seconds
from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.realtime_monitor.stream_models import StreamType
from hyper_smart_observer.realtime_monitor.subscriptions import Subscription
from hyper_smart_observer.realtime_monitor.websocket_manager import WebSocketManager


def test_backoff_is_monotonic_and_bounded():
    seq = [backoff_seconds(a, base=1.0, maximum=30.0) for a in range(1, 8)]
    assert seq == sorted(seq)          # non-decreasing
    assert max(seq) <= 30.0            # bounded, no runaway
    assert seq[0] >= 1.0


def test_snapshot_redelivered_on_reconnect_is_deduped():
    dedupe = EventDedupe()
    snapshot = {
        "channel": "userFills",
        "data": {"isSnapshot": True, "fills": [{"hash": "0xaaa", "tid": 1}, {"hash": "0xbbb", "tid": 2}]},
    }
    assert dedupe.accept_hyperliquid_message(snapshot) is True   # first time: new items
    # reconnect re-delivers the same snapshot -> all items already seen -> rejected
    assert dedupe.accept_hyperliquid_message(snapshot) is False
    # a mixed snapshot with one new item is still accepted
    mixed = {"channel": "userFills", "data": {"isSnapshot": True, "fills": [{"hash": "0xbbb", "tid": 2}, {"hash": "0xccc", "tid": 3}]}}
    assert dedupe.accept_hyperliquid_message(mixed) is True


def test_ws_qa_readiness_reports_bounded_read_only_source_health():
    manager = WebSocketManager(AppConfig(ws_max_user_subscriptions=10))
    subs = [Subscription(StreamType.USER_FILLS, user="0x" + "a" * 40)]

    report = manager.qa_readiness(subs, dry_run=True, duration_seconds=60)

    assert report.read_only is True
    assert report.bounded_duration is True
    assert report.subscription_count == 1
    assert report.unique_user_count == 1
    assert report.fallback_to_rest_polling is False
    assert report.stopped_reason == "bounded_read_only_ws_ready"
    assert report.source_health[0].status == "OK"


def test_ws_qa_readiness_falls_back_when_duration_unbounded():
    manager = WebSocketManager(AppConfig(ws_max_user_subscriptions=10))
    subs = [Subscription(StreamType.USER_FILLS, user="0x" + "a" * 40)]

    report = manager.qa_readiness(subs, dry_run=False, duration_seconds=None)

    assert report.fallback_to_rest_polling is True
    assert report.stopped_reason == "unbounded_duration_fallback_rest_polling"
    assert report.source_health[0].status == "FAIL"
