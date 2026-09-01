from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from hl_observer.alerts.spine import (
    AlertSpinePaths,
    AlertValidationError,
    CanonicalAlertWriter,
    CanonicalLedgerCorruption,
    build_alert_proposal,
)


def _writer(
    root: Path,
    *,
    clock: list[int] | None = None,
) -> CanonicalAlertWriter:
    now = clock if clock is not None else [10_000]
    return CanonicalAlertWriter(
        AlertSpinePaths.from_root(root / "alert-spine"),
        clock_ms=lambda: now[0],
    )


def _proposal(
    sequence: int,
    *,
    producer_id: str = "producer-a",
    producer_epoch: str = "epoch-a",
    source_id: str = "wire-a",
    source_uri: str | None = None,
    source_event_id: str | None = None,
    content: str | None = None,
    headline: str = "Same bounded headline",
    dedup_key: str | None = None,
    revision_of: str | None = None,
) -> dict:
    source_content = content or f"content:{source_id}:{sequence}"
    return build_alert_proposal(
        producer_id=producer_id,
        producer_epoch=producer_epoch,
        producer_seq=sequence,
        source_id=source_id,
        source_uri=(
            source_uri
            or f"https://example.invalid/{source_id}/{source_event_id or sequence}"
        ),
        source_content_hash=hashlib.sha256(source_content.encode()).hexdigest(),
        source_event_id=source_event_id,
        source_event_time_ms=500,
        observed_at_ms=1_000,
        fetched_at_ms=2_000,
        verified_at_ms=3_000,
        category="market_event",
        headline=headline,
        dedup_key=dedup_key,
        entity_ids=["asset:btc"],
        normalized_tickers=["BTC"],
        source_health_state="HEALTHY",
        freshness_state="FRESH",
        deterministic_score_components={"source": 1.0},
        policy_version="alert-idempotency.v26.1",
        ingestion_code_sha="d" * 40,
        revision_of=revision_of,
        payload={"content": source_content},
    )


def test_retry_identique_apres_24h_garde_un_effet_canonique(tmp_path: Path) -> None:
    clock = [10_000]
    writer = _writer(tmp_path, clock=clock)
    proposal = _proposal(0, source_event_id="wire-event-1")
    writer.producer("producer-a").submit(proposal)
    first = writer.process_pending()
    event = writer.read_ledger()[0]

    clock[0] += 24 * 60 * 60 * 1_000
    writer.producer("producer-a").submit(proposal)
    retry = writer.process_pending()

    assert first["accepted"] == 1
    assert retry["accepted"] == 0
    assert retry["deduplicated"] == 1
    assert writer.read_ledger() == [event]


def test_sequence_tardive_est_refusee_et_gap_est_explicite(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    writer.producer("producer-a").submit(_proposal(2))
    writer.process_pending()
    event = writer.read_ledger()[0]

    assert event["producer_expected_seq"] == 0
    assert event["producer_gap_detected"] is True
    assert event["producer_gap_size"] == 2

    writer.producer("producer-a").submit(_proposal(1))
    with pytest.raises(AlertValidationError, match="PRODUCER_SEQUENCE_OUT_OF_ORDER"):
        writer.process_pending()
    assert writer.read_ledger() == [event]


def test_titre_identique_de_deux_sources_reste_deux_evenements(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    writer.producer("producer-a").submit(
        _proposal(
            0,
            producer_id="producer-a",
            producer_epoch="epoch-a",
            source_id="wire-a",
            source_event_id="event-1",
            content="same content",
        )
    )
    writer.producer("producer-b").submit(
        _proposal(
            0,
            producer_id="producer-b",
            producer_epoch="epoch-b",
            source_id="wire-b",
            source_event_id="event-1",
            content="same content",
        )
    )
    writer.process_pending()
    events = writer.read_ledger()

    assert len(events) == 2
    assert events[0]["headline"] == events[1]["headline"]
    assert events[0]["source_id"] != events[1]["source_id"]
    assert events[0]["event_id"] != events[1]["event_id"]


def test_correction_meme_source_event_id_conserve_deux_identites(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    writer.producer("producer-a").submit(
        _proposal(0, source_event_id="stable-wire-id", content="version one")
    )
    writer.process_pending()
    original = writer.read_ledger()[0]
    writer.producer("producer-a").submit(
        _proposal(
            1,
            source_event_id="stable-wire-id",
            content="corrected version",
            revision_of=original["event_id"],
        )
    )
    writer.process_pending()
    events = writer.read_ledger()

    assert len(events) == 2
    assert events[0]["source_event_id"] == events[1]["source_event_id"]
    assert events[0]["event_id"] != events[1]["event_id"]
    assert events[1]["revision_of"] == events[0]["event_id"]


def test_fallback_dedup_est_stable_sans_id_source(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    stable_uri = "https://example.invalid/wire-a/stable-resource"
    first = _proposal(0, content="stable fallback content", source_uri=stable_uri)
    second = _proposal(1, content="stable fallback content", source_uri=stable_uri)
    assert first["dedup_key_origin"] == "CANONICAL_FALLBACK"
    assert first["dedup_key"] == second["dedup_key"]

    writer.producer("producer-a").submit(first)
    writer.process_pending()
    writer.producer("producer-a").submit(second)
    receipt = writer.process_pending()

    assert receipt["deduplicated"] == 1
    assert len(writer.read_ledger()) == 1


def test_curseurs_durables_et_replay_zero_donnent_le_meme_hash(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    for sequence in range(3):
        writer.producer("producer-a").submit(_proposal(sequence))
    writer.process_pending()
    first_projection = writer.rebuild_projection()
    writer_cursor = json.loads(writer.paths.writer_cursor_path.read_text(encoding="utf-8"))
    projection_cursor = json.loads(
        writer.paths.projection_cursor_path.read_text(encoding="utf-8")
    )

    assert writer_cursor["ledger_sequence"] == 3
    assert projection_cursor["ledger_sequence"] == 3
    assert writer_cursor["event_id"] == writer.read_ledger()[-1]["event_id"]

    writer.paths.projection_path.unlink()
    writer.paths.projection_cursor_path.unlink()
    replayed = writer.rebuild_projection()
    assert replayed["canonical_projection_hash"] == first_projection[
        "canonical_projection_hash"
    ]

    transported = _writer(tmp_path / "transported")
    transported.paths.ledger_path.parent.mkdir(parents=True)
    shutil.copy2(writer.paths.ledger_path, transported.paths.ledger_path)
    transported_projection = transported.rebuild_projection()
    assert transported_projection["canonical_projection_hash"] == first_projection[
        "canonical_projection_hash"
    ]


def test_curseur_forge_plus_loin_que_ledger_est_fail_closed(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    writer.producer("producer-a").submit(_proposal(0))
    writer.process_pending()
    cursor = json.loads(writer.paths.writer_cursor_path.read_text(encoding="utf-8"))
    cursor["ledger_sequence"] = 2
    writer.paths.writer_cursor_path.write_text(
        json.dumps(cursor, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(
        CanonicalLedgerCorruption,
        match="DURABLE_CURSOR_AHEAD_OF_LEDGER",
    ):
        writer.process_pending()
