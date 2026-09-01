from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from hl_observer.alerts.spine import (
    AlertSpinePaths,
    AlertValidationError,
    CanonicalAlertWriter,
    CanonicalLedgerCorruption,
    SingleWriterFileLock,
    WriterBusy,
    build_alert_proposal,
)


class SimulatedWriterKill(BaseException):
    pass


def _proposal(producer_id: str, sequence: int, *, dedup_key: str | None = None) -> dict:
    content = f"source-content:{producer_id}:{sequence}".encode()
    return build_alert_proposal(
        producer_id=producer_id,
        producer_epoch="test-epoch-1",
        producer_seq=sequence,
        source_id="source-primary",
        source_uri=f"https://example.invalid/{producer_id}/{sequence}",
        source_content_hash=hashlib.sha256(content).hexdigest(),
        observed_at_ms=1_000 + sequence,
        fetched_at_ms=2_000 + sequence,
        verified_at_ms=3_000 + sequence,
        category="market_event",
        headline=f"Alert {producer_id} {sequence}",
        dedup_key=dedup_key or f"{producer_id}:{sequence}",
        policy_version="alerts-test.v1",
        ingestion_code_sha="a" * 40,
        entity_ids=[f"asset:{producer_id}"],
        normalized_tickers=["btc"],
        source_health_state="HEALTHY",
        freshness_state="FRESH",
        deterministic_score_components={"source_quality": 0.8},
        payload={"symbol": "BTC", "score": sequence},
    )


def _writer(tmp_path: Path) -> CanonicalAlertWriter:
    return CanonicalAlertWriter(
        AlertSpinePaths.from_root(tmp_path / "alert-spine"),
        clock_ms=lambda: 10_000,
    )


def test_vingt_producteurs_concurrents_n_ecrasent_aucune_proposition(tmp_path: Path) -> None:
    writer = _writer(tmp_path)

    def submit(index: int) -> Path:
        producer_id = f"producer-{index:02d}"
        return writer.producer(producer_id).submit(_proposal(producer_id, index))

    with ThreadPoolExecutor(max_workers=20) as executor:
        paths = list(executor.map(submit, range(20)))

    assert len(set(paths)) == 20
    assert not writer.paths.ledger_path.exists()

    receipt = writer.process_pending()
    events = writer.read_ledger()

    assert receipt["accepted"] == 20
    assert receipt["deduplicated"] == 0
    assert [event["ledger_sequence"] for event in events] == list(range(1, 21))
    assert [event["producer_id"] for event in events] == sorted(
        event["producer_id"] for event in events
    )
    assert len({event["event_id"] for event in events}) == 20


def test_kill_apres_preparation_conserve_un_etat_rejouable(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    writer.producer("producer-a").submit(_proposal("producer-a", 1))

    def kill(_event: object) -> None:
        raise SimulatedWriterKill

    with pytest.raises(SimulatedWriterKill):
        writer.process_pending(after_prepare=kill)

    assert writer.read_ledger() == []
    assert len(list(writer.paths.inflight_root.glob("*/*.json"))) == 1
    assert len(list(writer.paths.pending_root.glob("*/*.json"))) == 1

    recovered = _writer(tmp_path).process_pending()

    assert recovered["accepted"] == 1
    assert recovered["ledger_count"] == 1


def test_kill_apres_append_avant_ack_ne_duplique_pas_evenement(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    writer.producer("producer-a").submit(_proposal("producer-a", 1))

    def kill(_event: object) -> None:
        raise SimulatedWriterKill

    with pytest.raises(SimulatedWriterKill):
        writer.process_pending(after_append=kill)

    event_before_restart = writer.read_ledger()[0]
    recovered = _writer(tmp_path).process_pending()
    events_after_restart = writer.read_ledger()

    assert recovered["accepted"] == 0
    assert recovered["deduplicated"] == 1
    assert events_after_restart == [event_before_restart]
    assert not list(writer.paths.inflight_root.glob("*/*.json"))
    assert not list(writer.paths.pending_root.glob("*/*.json"))


def test_capacite_producteur_reste_isolee_du_ledger_canonique(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    producer = writer.producer("producer-a")
    pending = producer.submit(_proposal("producer-a", 1))

    assert pending.is_relative_to(writer.paths.pending_root)
    assert not writer.paths.ledger_path.exists()
    assert not hasattr(producer, "ledger_path")

    forged = _proposal("producer-b", 2)
    with pytest.raises(AlertValidationError, match="PRODUCER_CAPABILITY_MISMATCH"):
        producer.submit(forged)
    assert not writer.paths.ledger_path.exists()


def test_projection_supprimee_est_reconstruite_integralement_du_ledger(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    for sequence in range(3):
        writer.producer("producer-a").submit(_proposal("producer-a", sequence))
    writer.process_pending()
    original = writer.rebuild_projection()
    writer.paths.projection_path.unlink()

    rebuilt = _writer(tmp_path).rebuild_projection()

    assert rebuilt == original
    assert rebuilt["alert_count"] == 3
    assert writer.paths.projection_path.is_file()


def test_verrou_os_interdit_deux_writers_simultanes(tmp_path: Path) -> None:
    lock_path = tmp_path / "writer.lock"

    with SingleWriterFileLock(lock_path), pytest.raises(
        WriterBusy, match="CANONICAL_WRITER_ALREADY_ACTIVE"
    ):
        SingleWriterFileLock(lock_path).acquire()


def test_ledger_partiel_est_refuse_sans_reparation_silencieuse(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    writer.paths.ledger_path.parent.mkdir(parents=True)
    writer.paths.ledger_path.write_bytes(b'{"schema_version":"incomplete"}')

    with pytest.raises(
        CanonicalLedgerCorruption,
        match="CANONICAL_LEDGER_TRAILING_PARTIAL_RECORD",
    ):
        writer.read_ledger()
