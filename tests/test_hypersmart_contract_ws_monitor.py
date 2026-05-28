import pytest
from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.realtime_monitor.websocket_manager import WebSocketManager
from hyper_smart_observer.realtime_monitor.subscriptions import Subscription
from hyper_smart_observer.realtime_monitor.stream_models import StreamType

def test_ws_monitor_plan_read_only():
    config = AppConfig(ws_monitor_enabled=True)
    manager = WebSocketManager(config)

    # Plan for all mids
    plan = manager.build_plan([Subscription(StreamType.ALL_MIDS)], dry_run=True)

    assert plan.dry_run is True
    assert len(plan.subscriptions) == 1
    assert "allMids" in str(plan.subscriptions[0].stream_type)
