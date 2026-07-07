from __future__ import annotations

from hl_observer.realtime_monitor.ws_supervisor import WsSupervisor
from hl_observer.sources.collection_recorder import CollectionRecorder
from hl_observer.sources.models import SourceStatus


def _snapshot_message():
    return {
        "channel": "userFills",
        "data": {
            "isSnapshot": True,
            "fills": [
                {"hash": "0xabc", "coin": "HYPE", "time": 1_700_000_000_000},
                {"hash": "0xdef", "coin": "BTC", "time": 1_700_000_000_100},
            ],
        },
    }


def test_v12_ws_supervisor_records_hl_ws_provenance_and_raw_payload():
    recorder = CollectionRecorder()
    supervisor = WsSupervisor(recorder=recorder)

    decision = supervisor.accept_message(_snapshot_message(), received_at_ms=1_700_000_001_000)
    source_id = CollectionRecorder.ws_source_id("userFills")
    health = recorder.registry.health(source_id, now_ms=1_700_000_001_100)
    summary = supervisor.source_health_summary(now_ms=1_700_000_001_100)

    assert decision.accepted
    assert health.status == SourceStatus.OK
    assert health.usable
    assert summary["ws_recorder"] == "enabled"
    assert summary["raw_events_stored"] == 1


def test_v12_ws_duplicate_snapshot_is_deduped_without_source_failure():
    recorder = CollectionRecorder()
    supervisor = WsSupervisor(recorder=recorder)
    message = _snapshot_message()

    first = supervisor.accept_message(message, received_at_ms=1_700_000_001_000)
    second = supervisor.accept_message(message, received_at_ms=1_700_000_002_000)
    source_id = CollectionRecorder.ws_source_id("userFills")
    health = recorder.registry.health(source_id, now_ms=1_700_000_002_100)

    assert first.accepted
    assert not second.accepted
    assert second.reason == "DUPLICATE_WS_SNAPSHOT"
    assert recorder.summary(now_ms=1_700_000_002_100)["raw_events_stored"] == 1
    assert health.status == SourceStatus.OK
    assert health.samples == 2


def test_v12_ws_supervisor_without_recorder_stays_compatible():
    supervisor = WsSupervisor()
    decision = supervisor.accept_message({"channel": "trades", "data": {"trade": 1}}, received_at_ms=10)
    summary = supervisor.source_health_summary(now_ms=20)

    assert decision.accepted
    assert summary["ws_recorder"] == "disabled"
    assert summary["sources"] == 0
