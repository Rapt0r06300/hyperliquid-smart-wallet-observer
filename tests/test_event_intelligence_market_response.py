from hl_observer.event_intelligence.external_event import ExternalEvent, ExternalEventType, SourceTier
from hl_observer.event_intelligence.runtime_pipeline import build_market_response_evidence


def test_market_response_fails_closed_without_market_data():
    event = ExternalEvent(
        event_id="event-1",
        source="usgs.earthquakes",
        source_tier=SourceTier.PRIMARY_OFFICIAL,
        event_type=ExternalEventType.NEWS,
        publication_ts_ms=1_100,
        retrieval_ts_ms=1_200,
        ingest_ts_ms=1_200,
        methodology_version="test-v1",
        raw_evidence_ref="sha256:event-1",
        entities=("BTC",),
    )

    evidence = build_market_response_evidence((event,), ())

    assert evidence["event_count"] == 1
    assert evidence["measured_reaction_count"] == 0
    assert evidence["proof_state"] == "UNMEASURABLE"
    assert evidence["proof_of_pnl_allowed"] is False
    assert evidence["real_execution"] is False
