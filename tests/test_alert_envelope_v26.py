from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hl_observer.alerts.spine import (
    EVENT_SCHEMA,
    AlertSpinePaths,
    AlertValidationError,
    CanonicalAlertWriter,
    CanonicalLedgerCorruption,
    build_alert_proposal,
)


def _writer(tmp_path: Path, *, now_ms: int = 4_000) -> CanonicalAlertWriter:
    return CanonicalAlertWriter(
        AlertSpinePaths.from_root(tmp_path / "alerts"),
        clock_ms=lambda: now_ms,
    )


def _proposal(
    sequence: int,
    *,
    dedup_key: str | None = None,
    source_event_time_ms: int | None = 500,
    expires_at_ms: int | None = 10_000,
    revision_of: str | None = None,
    retracts: str | None = None,
) -> dict:
    source_hash = hashlib.sha256(f"source:{sequence}".encode()).hexdigest()
    return build_alert_proposal(
        producer_id="news-primary",
        producer_epoch="test-epoch-1",
        producer_seq=sequence,
        source_id="primary-wire",
        source_uri=f"https://example.invalid/event/{sequence}",
        source_content_hash=source_hash,
        source_event_time_ms=source_event_time_ms,
        observed_at_ms=1_000 + sequence,
        fetched_at_ms=2_000 + sequence,
        verified_at_ms=3_000 + sequence,
        expires_at_ms=expires_at_ms,
        category="market_event",
        headline=f"Canonical event {sequence}",
        dedup_key=dedup_key or f"primary-wire:{sequence}",
        entity_ids=["asset:btc", "issuer:example"],
        normalized_tickers=["btc", "hype"],
        evidence_refs=[
            {
                "evidence_id": f"wire-{sequence}",
                "source_uri": f"https://example.invalid/event/{sequence}",
                "content_hash": source_hash,
            }
        ],
        source_health_state="HEALTHY",
        freshness_state="FRESH",
        deterministic_score_components={"directness": 1, "freshness": 0.9},
        model_opinion={"summary": "metadata only", "conviction": "HIGH"},
        policy_version="alert-admission.v26.1",
        ingestion_code_sha="b" * 40,
        revision_of=revision_of,
        retracts=retracts,
        payload={"symbol": "BTC", "kind": "news"},
    )


def test_enveloppe_canonique_est_complete_et_telemetrie_reste_dans_projection(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path)
    writer.producer("news-primary").submit(_proposal(1))
    writer.process_pending()

    event = writer.read_ledger()[0]
    projection = writer.rebuild_projection(displayed_at_ms=4_100)

    assert event["schema_version"] == EVENT_SCHEMA
    assert event["source_receipt_hash"] == hashlib.sha256(
        json.dumps(
            event["source_receipt"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    assert event["entity_ids"] == ["asset:btc", "issuer:example"]
    assert event["normalized_tickers"] == ["BTC", "HYPE"]
    assert event["source_health_state"] == "HEALTHY"
    assert event["freshness_state"] == "FRESH"
    assert event["model_opinion"]["authoritative"] is False
    assert event["policy_version"] == "alert-admission.v26.1"
    assert event["ingestion_code_sha"] == "b" * 40
    assert [item["state"] for item in event["lifecycle_receipt"]] == [
        "DETECTED",
        "FETCHED",
        "VERIFIED",
        "ADMITTED",
    ]
    assert event["lifecycle_state"] == "ADMITTED"
    assert "projected_at_ms" not in event
    assert "displayed_at_ms" not in event
    assert projection["projection_telemetry"] == {
        "projected_at_ms": 4_000,
        "displayed_at_ms": 4_100,
    }
    assert projection["alerts"][0]["projection_lifecycle_state"] == "PROJECTED"


def test_timestamps_impossibles_sont_refuses_avant_ledger(tmp_path: Path) -> None:
    with pytest.raises(AlertValidationError, match="SOURCE_EVENT_TIME_IMPOSSIBLE"):
        _proposal(1, source_event_time_ms=1_002)

    proposal = _proposal(2)
    proposal["fetched_at_ms"] = proposal["observed_at_ms"] - 1
    proposal.pop("proposal_id")
    with pytest.raises(AlertValidationError, match="TIMESTAMP_ORDER_INVALID"):
        _writer(tmp_path).producer("news-primary").submit(proposal)

    writer = _writer(tmp_path, now_ms=2_500)
    writer.producer("news-primary").submit(_proposal(3))
    with pytest.raises(AlertValidationError, match="ADMITTED_BEFORE_VERIFIED"):
        writer.process_pending()
    assert not writer.paths.ledger_path.exists()


def test_provenance_alteree_dans_le_ledger_est_refusee(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    writer.producer("news-primary").submit(_proposal(1))
    writer.process_pending()
    event = writer.read_ledger()[0]
    event["source_uri"] = "https://example.invalid/tampered"
    writer.paths.ledger_path.write_text(
        json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        CanonicalLedgerCorruption,
        match="CANONICAL_SOURCE_RECEIPT_INVALID",
    ):
        writer.read_ledger()


def test_correction_et_retraction_preservent_evenement_original(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    writer.producer("news-primary").submit(_proposal(1))
    writer.process_pending()
    original = writer.read_ledger()[0]

    writer.producer("news-primary").submit(
        _proposal(2, revision_of=original["event_id"])
    )
    writer.process_pending()
    correction = writer.read_ledger()[1]
    writer.producer("news-primary").submit(
        _proposal(3, retracts=original["event_id"])
    )
    writer.process_pending()

    events = writer.read_ledger()
    projection = writer.rebuild_projection()
    projected = {item["event_id"]: item for item in projection["alerts"]}

    assert len(events) == 3
    assert events[0] == original
    assert correction["revision_of"] == original["event_id"]
    assert events[2]["retracts"] == original["event_id"]
    assert projected[original["event_id"]]["projection_lifecycle_state"] == "RETRACTED"
    assert projected[correction["event_id"]]["projection_lifecycle_state"] == "PROJECTED"

    writer.producer("news-primary").submit(
        _proposal(4, revision_of=original["event_id"])
    )
    with pytest.raises(
        AlertValidationError,
        match="REVISION_TARGET_ALREADY_RETRACTED",
    ):
        writer.process_pending()
    assert len(writer.read_ledger()) == 3


def test_reference_inconnue_et_transition_de_ledger_corrompue_sont_refusees(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path)
    writer.producer("news-primary").submit(_proposal(1, revision_of="c" * 64))
    with pytest.raises(AlertValidationError, match="REVISION_OF_TARGET_UNKNOWN"):
        writer.process_pending()
    assert not writer.paths.ledger_path.exists()

    clean = _writer(tmp_path / "clean")
    clean.producer("news-primary").submit(_proposal(2))
    clean.process_pending()
    event = clean.read_ledger()[0]
    event["lifecycle_receipt"][2]["state"] = "ADMITTED"
    clean.paths.ledger_path.write_text(
        json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(
        CanonicalLedgerCorruption,
        match="LIFECYCLE_TRANSITION_INVALID",
    ):
        clean.read_ledger()


def test_expiration_est_derivee_sans_muter_evenement(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    writer.producer("news-primary").submit(_proposal(1, expires_at_ms=5_000))
    writer.process_pending()
    admitted = writer.read_ledger()[0]

    expired = _writer(tmp_path, now_ms=6_000).rebuild_projection()

    assert admitted["lifecycle_state"] == "ADMITTED"
    assert expired["alerts"][0]["projection_lifecycle_state"] == "EXPIRED"
    assert _writer(tmp_path, now_ms=6_000).read_ledger()[0] == admitted
