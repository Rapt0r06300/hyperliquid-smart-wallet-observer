import pytest
from hyper_smart_observer.realtime_monitor.websocket_manager import WebSocketManager
from hyper_smart_observer.realtime_monitor.subscriptions import Subscription
from hyper_smart_observer.realtime_monitor.stream_models import StreamType
from hyper_smart_observer.app.config import AppConfig

@pytest.mark.contract
def test_contract_websocket_max_users_limit():
    """
    Contract: WebSocket monitor must not exceed 10 unique users for user-specific streams.
    """
    config = AppConfig(ws_max_user_subscriptions=10)
    manager = WebSocketManager(config)

    # Create 11 unique user subscriptions
    subs = [
        Subscription(StreamType.USER_FILLS, user=f"0x{i:040}")
        for i in range(1, 12)
    ]

    plan = manager.build_plan(subs, dry_run=True)

    # The plan should have flagged an issue or truncated the subscriptions
    # Current implementation in hyper_smart_observer might be basic,
    # let's verify if it catches it via planner validation.
    assert len(plan.subscriptions) <= 10, "Contract: Must not exceed 10 unique users"
    if len(subs) > 10 and len(plan.subscriptions) < len(subs):
         assert any("limit" in w.lower() or "unique" in w.lower() for w in plan.warnings), \
            "Contract: Should have a warning when limit is reached"

@pytest.mark.contract
def test_contract_websocket_duration_required():
    """
    Contract: WebSocket monitor MUST have a bounded duration if not dry-run.
    """
    config = AppConfig(ws_monitor_enabled=True)
    manager = WebSocketManager(config)
    subs = [Subscription(StreamType.ALL_MIDS)]

    # Try to build a plan without duration and dry_run=False
    plan = manager.build_plan(subs, dry_run=False, duration_seconds=None)
    assert any("duration" in w.lower() for w in plan.warnings), \
        "Contract: Non-dry-run WebSocket requires a bounded duration"
