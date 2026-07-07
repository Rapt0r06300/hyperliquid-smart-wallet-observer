from __future__ import annotations

from hl_observer.collection.backoff import BackoffPolicy
from hl_observer.realtime_monitor import (
    WS_MAX_MESSAGES_PER_MINUTE,
    WS_MAX_NEW_CONNECTIONS_PER_MINUTE,
    WS_MAX_SUBSCRIPTIONS,
    WS_MAX_UNIQUE_USERS,
    WsSupervisor,
)


def test_ws_subscription_plan_is_read_only_and_allows_bounded_shortlist() -> None:
    wallets = [f"0x{i:040x}" for i in range(WS_MAX_UNIQUE_USERS)]

    plan = WsSupervisor().plan_subscriptions(wallets, market_channels=25)

    assert plan.allowed is True
    assert plan.read_only is True
    assert plan.execution == "forbidden"
    assert plan.unique_user_count == 10
    assert plan.subscription_count == 35
    assert plan.fallback_to_rest is False
    assert "WS_USER_CAP_REACHED" in plan.warnings


def test_ws_subscription_plan_refuses_over_ten_unique_users() -> None:
    wallets = [f"0x{i:040x}" for i in range(WS_MAX_UNIQUE_USERS + 1)]

    plan = WsSupervisor().plan_subscriptions(wallets)

    assert plan.allowed is False
    assert plan.fallback_to_rest is True
    assert "WS_UNIQUE_USER_CAP_EXCEEDED" in plan.refusal_reasons


def test_ws_subscription_plan_refuses_subscription_and_message_caps() -> None:
    plan = WsSupervisor().plan_subscriptions(
        [f"0x{i:040x}" for i in range(3)],
        market_channels=WS_MAX_SUBSCRIPTIONS,
        messages_per_minute=WS_MAX_MESSAGES_PER_MINUTE + 1,
        new_connections_per_minute=WS_MAX_NEW_CONNECTIONS_PER_MINUTE + 1,
    )

    assert plan.allowed is False
    assert "WS_SUBSCRIPTION_CAP_EXCEEDED" in plan.refusal_reasons
    assert "WS_MESSAGES_PER_MINUTE_CAP_EXCEEDED" in plan.refusal_reasons
    assert "WS_NEW_CONNECTIONS_PER_MINUTE_CAP_EXCEEDED" in plan.refusal_reasons


def test_ws_snapshot_dedupe_is_item_level_not_whole_payload_only() -> None:
    supervisor = WsSupervisor()
    snapshot = {
        "channel": "userFills",
        "data": {"isSnapshot": True, "fills": [{"hash": "0xaaa", "tid": 1}, {"hash": "0xbbb", "tid": 2}]},
    }
    duplicate_snapshot = {
        "channel": "userFills",
        "data": {"isSnapshot": True, "fills": [{"hash": "0xaaa", "tid": 1}, {"hash": "0xbbb", "tid": 2}]},
    }
    mixed_snapshot = {
        "channel": "userFills",
        "data": {"isSnapshot": True, "fills": [{"hash": "0xbbb", "tid": 2}, {"hash": "0xccc", "tid": 3}]},
    }

    assert supervisor.accept_message(snapshot, received_at_ms=1_000).accepted is True
    duplicate = supervisor.accept_message(duplicate_snapshot, received_at_ms=1_100)
    assert duplicate.accepted is False
    assert duplicate.reason == "DUPLICATE_WS_SNAPSHOT"
    assert supervisor.accept_message(mixed_snapshot, received_at_ms=1_200).accepted is True
    assert supervisor.accepted_events == 2
    assert supervisor.duplicate_events == 1


def test_ws_heartbeat_stale_requests_rest_gap_recovery() -> None:
    supervisor = WsSupervisor(heartbeat_max_age_ms=500)
    supervisor.accept_message({"channel": "allMids", "data": {"mids": {"BTC": "100"}}}, received_at_ms=1_000)

    fresh = supervisor.gap_recovery_decision(now_ms=1_200)
    stale = supervisor.gap_recovery_decision(now_ms=1_700)

    assert fresh.needs_gap_recovery is False
    assert fresh.reason == "NO_GAP_RECOVERY_NEEDED"
    assert stale.needs_gap_recovery is True
    assert stale.reason == "HEARTBEAT_STALE_REST_GAP_RECOVERY"


def test_ws_reconnect_backoff_is_bounded_and_resets_after_message() -> None:
    supervisor = WsSupervisor(backoff_policy=BackoffPolicy(base_seconds=1.0, max_seconds=8.0, jitter_ratio=0.0))

    delays = [supervisor.next_reconnect_delay() for _ in range(5)]
    assert delays == [1.0, 2.0, 4.0, 8.0, 8.0]

    supervisor.accept_message({"channel": "allMids", "data": {"mids": {"ETH": "10"}}}, received_at_ms=2_000)
    assert supervisor.reconnect_attempt == 0
    assert supervisor.next_reconnect_delay() == 1.0
