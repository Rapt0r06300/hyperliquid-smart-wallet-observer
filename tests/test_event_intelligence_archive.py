from __future__ import annotations

import json

import pytest

from hl_observer.event_intelligence import (
    EventArchiveCorruptError,
    EventIntelligenceArchive,
    ExternalEvent,
    ExternalEventType,
    SourceTier,
    WorldMonitorEvent,
    evaluate_worldmonitor_health,
)
from hl_observer.realtime.source_health import (
    CRITICAL,
    DATA_INCOMPLETE,
    HEALTHY,
    NO_FRESH_SIGNAL,
    STALE,
)


def _row(
    event_id: str,
    *,
    ingest_ts_ms: int = 10_000,
    coverage_state: str = "complete",
) -> WorldMonitorEvent:
    event = ExternalEvent(
        event_id=event_id,
        source="worldmonitor.news",
        event_type=ExternalEventType.NEWS,
        source_tier=SourceTier.AGGREGATOR,
        retrieval_ts_ms=ingest_ts_ms,
        ingest_ts_ms=ingest_ts_ms,
        methodology_version="test-v1",
        raw_evidence_ref=f"ref:{event_id}",
        corroboration_count=2,
    )
    return WorldMonitorEvent(
        event=event,
        kind="news",
        publisher="Reuters",
        source_count=2,
        importance_score=80.0,
        credibility_score=90.0,
        coverage_state=coverage_state,
    )


def test_archive_is_append_only_deduped_and_reopenable(tmp_path) -> None:
    path = tmp_path / "events_r2.jsonl"
    archive = EventIntelligenceArchive(path)

    first = archive.append(_row("event-1"))
    duplicate = archive.append(_row("event-1"))
    second = archive.append(_row("event-2", ingest_ts_ms=10_100))

    assert first.appended is True
    assert first.sequence == 1
    assert duplicate.appended is False
    assert duplicate.reason == "DUPLICATE_EVENT"
    assert second.appended is True
    assert second.sequence == 2
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2

    reopened = EventIntelligenceArchive(path)
    assert reopened.count == 2
    assert reopened.last_record_sha256 == second.record_sha256
    again = reopened.append(_row("event-2", ingest_ts_ms=10_100))
    assert again.appended is False


def test_archive_hash_chain_detects_tampering(tmp_path) -> None:
    path = tmp_path / "events_r2.jsonl"
    archive = EventIntelligenceArchive(path)
    archive.append(_row("event-1"))
    archive.append(_row("event-2"))

    records = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
    ]
    records[0]["payload"]["importance_score"] = 999
    path.write_text(
        "\n".join(
            json.dumps(record, sort_keys=True, separators=(",", ":"))
            for record in records
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(EventArchiveCorruptError, match="HASH_INVALID"):
        EventIntelligenceArchive(path)


def test_archive_contains_no_source_article_text_fields(tmp_path) -> None:
    path = tmp_path / "events_r2.jsonl"
    EventIntelligenceArchive(path).append(_row("event-1"))
    record = json.loads(path.read_text(encoding="utf-8").strip())
    payload = record["payload"]
    forbidden = {"headline", "title", "snippet", "body", "content", "summary", "text"}
    assert forbidden.isdisjoint(payload)
    assert record["schema"] == "alina.event_intelligence_archive.v1"
    assert len(record["payload_sha256"]) == 64
    assert len(record["record_sha256"]) == 64


def test_worldmonitor_health_is_healthy_only_with_fresh_signal() -> None:
    health = evaluate_worldmonitor_health(
        [_row("fresh", ingest_ts_ms=9_900)],
        coverage_state="complete",
        last_fetch_ms=9_950,
        now_ms=10_000,
        max_age_ms=1_000,
    )
    assert health.status == HEALTHY
    assert health.techniquement_sain is True
    assert health.produit_des_signaux_frais is True
    assert health.utilisable is True


def test_worldmonitor_health_distinguishes_no_signal_stale_partial_and_down() -> None:
    no_signal = evaluate_worldmonitor_health(
        [],
        coverage_state="complete",
        last_fetch_ms=9_950,
        now_ms=10_000,
        max_age_ms=1_000,
    )
    assert no_signal.status == NO_FRESH_SIGNAL
    assert no_signal.techniquement_sain is True
    assert no_signal.utilisable is False

    stale = evaluate_worldmonitor_health(
        [_row("stale", ingest_ts_ms=8_000, coverage_state="stale")],
        coverage_state="stale",
        last_fetch_ms=9_950,
        now_ms=10_000,
        max_age_ms=1_000,
    )
    assert stale.status == STALE
    assert stale.utilisable is False

    partial = evaluate_worldmonitor_health(
        [_row("partial", ingest_ts_ms=9_900)],
        coverage_state="partial",
        last_fetch_ms=9_950,
        now_ms=10_000,
        max_age_ms=1_000,
    )
    assert partial.status == DATA_INCOMPLETE
    assert partial.utilisable is False

    down = evaluate_worldmonitor_health(
        [],
        coverage_state="unavailable",
        last_fetch_ms=None,
        now_ms=10_000,
        max_age_ms=1_000,
        fetch_ok=False,
    )
    assert down.status == CRITICAL
    assert down.utilisable is False


def test_future_fetch_or_future_event_is_critical_clock_failure() -> None:
    future_fetch = evaluate_worldmonitor_health(
        [],
        coverage_state="complete",
        last_fetch_ms=10_100,
        now_ms=10_000,
        max_age_ms=1_000,
    )
    assert future_fetch.status == CRITICAL

    future_event = evaluate_worldmonitor_health(
        [_row("future", ingest_ts_ms=10_100)],
        coverage_state="complete",
        last_fetch_ms=10_000,
        now_ms=10_000,
        max_age_ms=1_000,
    )
    assert future_event.status == CRITICAL
