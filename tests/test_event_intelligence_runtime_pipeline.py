from hl_observer.event_intelligence.external_event import (
    ExternalEvent,
    ExternalEventType,
    SourceTier,
)
from hl_observer.event_intelligence.runtime_pipeline import (
    build_research_protocol_evidence,
    build_runtime_evidence,
)


def _event(event_id: str, source: str, tier: SourceTier, ingest: int) -> ExternalEvent:
    return ExternalEvent(
        event_id=event_id,
        source=source,
        event_type=ExternalEventType.NEWS,
        source_tier=tier,
        publication_ts_ms=ingest - 2,
        retrieval_ts_ms=ingest - 1,
        ingest_ts_ms=ingest,
        methodology_version="test-v1",
        raw_evidence_ref=f"sha256:{event_id}",
        entities=("BTC",),
    )


def test_runtime_evidence_is_causal_read_only_and_clustered():
    rows = (
        _event("same-story-a", "primary.example", SourceTier.PRIMARY_OFFICIAL, 1_000),
        _event("same-story-b", "aggregator.example", SourceTier.AGGREGATOR, 1_010),
    )
    result = build_runtime_evidence(
        rows,
        now_ms=2_000,
        expected_sources=("primary.example", "aggregator.example"),
        max_source_age_ms=2_000,
    )
    assert result["schema"] == "alina.event_intelligence_runtime_evidence.v1"
    assert result["accepted_event_count"] == 2
    assert result["proof_state"] == "STRUCTURAL_ONLY"
    assert result["proof_of_pnl_allowed"] is False
    assert result["paper_only"] is True
    assert result["read_only"] is True
    assert result["real_execution"] is False
    assert result["source_health"]["primary.example"]["gap"] is None


def test_future_event_is_rejected_and_cannot_become_pnl_proof():
    result = build_runtime_evidence(
        (_event("future", "primary.example", SourceTier.PRIMARY_OFFICIAL, 5_000),),
        now_ms=2_000,
        expected_sources=("primary.example",),
    )
    assert result["accepted_event_count"] == 0
    assert result["rejection_counts"] == {"FUTURE_INFORMATION": 1}
    assert result["proof_of_pnl_allowed"] is False


def test_empty_research_protocol_is_explicitly_unmeasurable():
    result = build_research_protocol_evidence(
        (),
        now_ms=2_000,
        methodology_version="test-v1",
        config={"family": "lead_lag"},
    )
    assert result["observation_count"] == 0
    assert result["proof_state"] == "UNMEASURABLE"
    assert result["proof_of_pnl_allowed"] is False
    assert result["forward_count"] == 0
