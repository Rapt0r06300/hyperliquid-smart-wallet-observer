from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.realtime_monitor.stream_models import StreamType
from hyper_smart_observer.realtime_monitor.subscriptions import Subscription
from hyper_smart_observer.realtime_monitor.websocket_manager import WebSocketManager


def test_ws_monitor_readonly_dry_run_plan():
    plan = WebSocketManager(AppConfig()).build_plan(
        [Subscription(StreamType.TRADES, coin="BTC")],
        dry_run=True,
        duration_seconds=10,
    )

    assert plan.dry_run is True
    assert plan.subscriptions[0].stream == StreamType.TRADES


def test_ws_monitor_refuses_unbounded_non_dry_run():
    plan = WebSocketManager(AppConfig()).build_plan(
        [Subscription(StreamType.ALL_MIDS)],
        dry_run=False,
        duration_seconds=None,
    )

    assert any("requires a bounded duration" in warning for warning in plan.warnings)
