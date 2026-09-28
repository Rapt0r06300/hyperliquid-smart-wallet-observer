from hl_observer.event_intelligence.external_event import ExternalEvent, ExternalEventType, SourceTier
from hl_observer.event_intelligence.runtime_pipeline import build_market_response_evidence


def test_market_response_fails_closed_without_market_data():
    event = ExternalEvent(
        event_id="event-1",
        source="usgs.earthquakes",
        source_event_id="source-1",
        source_tier=SourceTier.PRIMARY_OFFICIAL,
        event_type=ExternalEventType.NATURAL_HAZARD,
        event_ts_ms=1_000,
        publish_ts_ms=1_100,
        retrieval_ts_ms=1_200,
        ingest_ts_ms=1_200,
        title="Earthquake",
        summary="",
        entities=("BTC",),
        assets=("BTC",),
        classification_confidence=0.9,
        corroboration_count=1,
    )

    evidence = build_market_response_evidence((event,), ())

    assert evidence["event_count"] == 1
    assert evidence["measured_reaction_count"] == 0
    assert evidence["proof_state"] == "UNMEASURABLE"
    assert evidence["proof_of_pnl_allowed"] is False
    assert evidence["real_execution"] is False
