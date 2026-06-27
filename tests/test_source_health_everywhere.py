"""Phase 11 (canonical): one SourceHealth model with the mandated fields, plus
proof it is surfaced in the snapshot engine and the dashboard."""

from __future__ import annotations

import inspect

from hyper_smart_observer.pipeline.source_health import (
    STATUS_DEGRADED,
    STATUS_FAIL,
    STATUS_OK,
    SourceHealth,
    build_source_health,
)

MANDATED = {
    "name", "status", "latency_ms", "source_ts", "local_received_ts",
    "staleness_ms", "retry_count", "rate_budget", "degraded_reason", "raw_ref",
}


def test_source_health_has_all_mandated_fields():
    sh = SourceHealth(name="info.l2Book", status=STATUS_OK)
    assert MANDATED.issubset(set(sh.__dataclass_fields__))


def test_status_ok_degraded_fail_paths():
    ok = build_source_health("info.allMids", source_ts=1000, local_received_ts=1100, latency_ms=100)
    assert ok.status == STATUS_OK and ok.staleness_ms == 100
    degraded = build_source_health("info.l2Book", source_ts=0, local_received_ts=20_000, max_staleness_ms=10_000)
    assert degraded.status == STATUS_DEGRADED and degraded.degraded_reason
    failed = build_source_health("ws.userFills", ok=False)
    assert failed.status == STATUS_FAIL and failed.degraded_reason


def test_source_health_surfaced_in_engine_and_dashboard():
    from hyper_smart_observer.copy_mode import snapshot_engine
    from hyper_smart_observer.dashboard import exporter
    assert "_write_source_health" in inspect.getsource(snapshot_engine)
    assert "_source_health_table" in inspect.getsource(exporter)
