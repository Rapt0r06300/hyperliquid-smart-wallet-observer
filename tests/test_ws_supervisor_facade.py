"""Phase 10: unified WS supervisor composes reconnect/dedupe/heartbeat correctly."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hyper_smart_observer.realtime_monitor.ws_supervisor import WsSupervisor


def test_backoff_is_bounded_and_increasing():
    s = WsSupervisor()
    d1, d2, d3 = s.next_reconnect_delay(), s.next_reconnect_delay(), s.next_reconnect_delay()
    assert d1 <= d2 <= d3 and d3 <= 30.0


def test_snapshot_dedupe_and_heartbeat_reset():
    s = WsSupervisor(heartbeat_max_age_s=30)
    assert s.should_fallback_to_rest() is True  # never seen -> REST
    snap = {"channel": "userFills", "data": {"isSnapshot": True, "fills": [{"hash": "0x1", "tid": 1}]}}
    assert s.accept_message(snap) is True       # first time
    assert s.accept_message(snap) is False      # reconnect re-delivery deduped
    assert s.reconnect_attempt == 0             # accepting a message resets backoff
    assert s.should_fallback_to_rest() is False  # fresh now


def test_user_streams_capped_at_10():
    s = WsSupervisor()
    assert s.clamp_user_streams([f"0x{i:040x}" for i in range(25)]) == [f"0x{i:040x}" for i in range(10)]
