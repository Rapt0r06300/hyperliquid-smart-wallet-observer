from __future__ import annotations

from hl_observer.release.quality_gates import (
    GATE_BLOCKED,
    GATE_OK,
    GATE_WARN,
    _realtime_gate_status,
    _runtime_write_gate_status,
)
from hl_observer.runtime.write_diagnostics import (
    RUNTIME_WRITE_BLOCKED,
    RUNTIME_WRITE_OK,
    RUNTIME_WRITE_WARN,
)


def test_runtime_write_ok_maps_to_quality_gate_ok() -> None:
    assert _runtime_write_gate_status(RUNTIME_WRITE_OK) == GATE_OK


def test_runtime_write_warn_maps_to_quality_gate_warn() -> None:
    assert _runtime_write_gate_status(RUNTIME_WRITE_WARN) == GATE_WARN


def test_runtime_write_blocked_maps_to_quality_gate_blocked() -> None:
    assert _runtime_write_gate_status(RUNTIME_WRITE_BLOCKED) == GATE_BLOCKED


def test_realtime_live_statuses_map_to_quality_gate_ok() -> None:
    assert _realtime_gate_status("LIVE_FROM_LOCAL_LOGS") == GATE_OK
    assert _realtime_gate_status("LIVE_REPLAY_FROM_LOCAL_LOGS") == GATE_OK


def test_realtime_stale_maps_to_quality_gate_blocked() -> None:
    assert _realtime_gate_status("STALE") == GATE_BLOCKED


def test_realtime_unknown_status_maps_to_quality_gate_warn() -> None:
    assert _realtime_gate_status("UNKNOWN") == GATE_WARN
