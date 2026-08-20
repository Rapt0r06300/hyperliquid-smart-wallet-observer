from __future__ import annotations

from hl_observer.copy_mode.copy_session_controller import (
    CopySession,
    CopySessionState,
    pause_copy_session,
    start_copy_session,
    stop_copy_session,
)


def test_copy_session_lifecycle_is_local_paper_only_and_immutable() -> None:
    original = CopySession("s1")
    assert original.state is CopySessionState.STOPPED
    assert original.paper_only is True
    assert original.external_action is False
    assert original.started_at_ms is None
    assert original.stopped_at_ms is None

    started = start_copy_session(original, now_ms=123.9)
    assert original.state is CopySessionState.STOPPED
    assert started.state is CopySessionState.RUNNING
    assert started.started_at_ms == 123
    assert started.stopped_at_ms is None
    assert started.reason == "LOCAL_START"

    paused = pause_copy_session(started)
    assert paused.state is CopySessionState.PAUSED
    assert paused.reason == "LOCAL_PAUSE"
    assert paused.started_at_ms == 123

    stopped = stop_copy_session(paused, now_ms=456.8)
    assert stopped.state is CopySessionState.STOPPED
    assert stopped.stopped_at_ms == 456
    assert stopped.reason == "LOCAL_STOP"
    assert stopped.paper_only is True
    assert stopped.external_action is False


def test_custom_pause_and_stop_reasons_are_preserved() -> None:
    session = CopySession("s2", state=CopySessionState.RUNNING, started_at_ms=1)
    paused = pause_copy_session(session, reason="RISK_PAUSE")
    stopped = stop_copy_session(paused, now_ms=2, reason="USER_STOP")
    assert paused.reason == "RISK_PAUSE"
    assert stopped.reason == "USER_STOP"
