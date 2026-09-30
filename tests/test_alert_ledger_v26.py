from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from hl_observer.alerts.spine import (
    LEDGER_LATEST_SCHEMA,
    AlertSpinePaths,
    CanonicalAlertWriter,
    CanonicalLedgerCorruption,
    build_alert_proposal,
)


def _proposal(sequence: int) -> dict[str, object]:
    return build_alert_proposal(
        producer_id="ledger-producer",
        producer_epoch="ledger-epoch-1",
        producer_seq=sequence,
        source_id="ledger-source",
        source_uri=f"https://example.invalid/ledger/{sequence}",
        source_content_hash=hashlib.sha256(str(sequence).encode()).hexdigest(),
        observed_at_ms=1_000 + sequence,
        fetched_at_ms=2_000 + sequence,
        verified_at_ms=3_000 + sequence,
        category="MARKET_EVENT",
        headline=f"Ledger alert {sequence}",
        dedup_key=f"ledger:{sequence}",
        policy_version="alert-ledger-test.v1",
        ingestion_code_sha="b" * 40,
        source_health_state="HEALTHY",
        freshness_state="FRESH",
        payload={"sequence": sequence},
    )


def _writer(root: Path, *, rotate_bytes: int) -> CanonicalAlertWriter:
    return CanonicalAlertWriter(
        AlertSpinePaths.from_root(root),
        clock_ms=lambda: 10_000,
        ledger_rotate_bytes=rotate_bytes,
    )


def _submit(writer: CanonicalAlertWriter, *sequences: int) -> None:
    producer = writer.producer("ledger-producer")
    for sequence in sequences:
        producer.submit(_proposal(sequence))


def test_rotation_jsonl_cree_des_segments_immuables_hashes(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine", rotate_bytes=1)
    _submit(writer, 0, 1, 2)

    receipt = writer.process_pending()
    segments = sorted(writer.paths.ledger_segments_root.glob("*.jsonl"))
    pointer = json.loads(
        writer.paths.ledger_latest_pointer_path.read_text(encoding="utf-8")
    )

    assert receipt["accepted"] == 3
    assert len(segments) == 3
    assert not writer.paths.ledger_path.exists()
    assert [event["ledger_sequence"] for event in writer.read_ledger()] == [1, 2, 3]
    assert pointer["schema_version"] == LEDGER_LATEST_SCHEMA
    assert pointer["storage_kind"] == "NATIVE_JSONL"
    assert pointer["ledger_sequence"] == 3
    assert pointer["database_promoted"] is False
    assert len(pointer["segments"]) == 3
    for segment, segment_receipt in zip(segments, pointer["segments"], strict=True):
        raw = segment.read_bytes()
        assert segment_receipt["name"] == segment.name
        assert segment_receipt["sha256"] == hashlib.sha256(raw).hexdigest()
        assert segment_receipt["bytes"] == len(raw)


def test_alteration_segment_est_refusee_par_checksum(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine", rotate_bytes=1)
    _submit(writer, 0)
    writer.process_pending()
    segment = next(writer.paths.ledger_segments_root.glob("*.jsonl"))
    segment.write_bytes(segment.read_bytes() + b" ")

    with pytest.raises(
        CanonicalLedgerCorruption,
        match="CANONICAL_SEGMENT_CHECKSUM_MISMATCH",
    ):
        writer.read_ledger()


def test_pointeur_latest_est_atomique_et_refuse_une_fausse_empreinte(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path / "spine", rotate_bytes=10_000_000)
    _submit(writer, 0)
    writer.process_pending()
    pointer_path = writer.paths.ledger_latest_pointer_path
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))

    assert pointer_path.is_file()
    assert not pointer_path.with_suffix(pointer_path.suffix + ".tmp").exists()
    pointer["active_sha256"] = "0" * 64
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

    with pytest.raises(
        CanonicalLedgerCorruption,
        match="CANONICAL_LATEST_POINTER_STORAGE_MISMATCH",
    ):
        writer.read_ledger()


def test_pointeur_en_retard_apres_crash_est_accepte_puis_repare(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path / "spine", rotate_bytes=10_000_000)
    _submit(writer, 0)
    writer.process_pending()
    pointer_path = writer.paths.ledger_latest_pointer_path
    stale_pointer = pointer_path.read_bytes()
    _submit(writer, 1)
    writer.process_pending()
    pointer_path.write_bytes(stale_pointer)

    assert len(writer.read_ledger()) == 2
    writer.process_pending()
    repaired = json.loads(pointer_path.read_text(encoding="utf-8"))

    assert repaired["ledger_sequence"] == 2
    assert repaired["event_id"] == writer.read_ledger()[-1]["event_id"]


def test_pointeur_en_avance_sur_le_ledger_est_refuse(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine", rotate_bytes=10_000_000)
    _submit(writer, 0)
    writer.process_pending()
    pointer_path = writer.paths.ledger_latest_pointer_path
    pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    pointer["ledger_sequence"] = 2
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")

    with pytest.raises(
        CanonicalLedgerCorruption,
        match="CANONICAL_LATEST_POINTER_AHEAD",
    ):
        writer.read_ledger()


def test_curseur_durable_refuse_schema_sequence_et_hash_alteres(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine", rotate_bytes=10_000_000)
    _submit(writer, 0)
    writer.process_pending()
    events = writer.read_ledger()
    cursor_path = tmp_path / "cursor.json"

    writer._write_cursor(cursor_path, consumer="coverage-audit", events=events)
    original = json.loads(cursor_path.read_text(encoding="utf-8"))
    assert writer._validate_cursor(
        cursor_path,
        consumer="coverage-audit",
        events=events,
    ) == 1

    cursor_path.write_text("{", encoding="utf-8")
    with pytest.raises(CanonicalLedgerCorruption, match="DURABLE_CURSOR_INVALID"):
        writer._validate_cursor(cursor_path, consumer="coverage-audit", events=events)

    tampered = dict(original)
    tampered["real_execution"] = True
    cursor_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(CanonicalLedgerCorruption, match="DURABLE_CURSOR_SCHEMA_INVALID"):
        writer._validate_cursor(cursor_path, consumer="coverage-audit", events=events)

    tampered = dict(original)
    tampered["ledger_sequence"] = "not-an-int"
    cursor_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(
        CanonicalLedgerCorruption,
        match="DURABLE_CURSOR_SEQUENCE_INVALID",
    ):
        writer._validate_cursor(cursor_path, consumer="coverage-audit", events=events)

    tampered = dict(original)
    tampered["ledger_sequence"] = 2
    cursor_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(
        CanonicalLedgerCorruption,
        match="DURABLE_CURSOR_AHEAD_OF_LEDGER",
    ):
        writer._validate_cursor(cursor_path, consumer="coverage-audit", events=events)

    tampered = dict(original)
    tampered["ledger_prefix_hash"] = "0" * 64
    cursor_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(
        CanonicalLedgerCorruption,
        match="DURABLE_CURSOR_LEDGER_MISMATCH",
    ):
        writer._validate_cursor(cursor_path, consumer="coverage-audit", events=events)


def test_pointeur_latest_refuse_corruption_schema_sequence_et_prefixe(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path / "spine", rotate_bytes=10_000_000)
    _submit(writer, 0)
    writer.process_pending()
    events = writer.read_ledger()
    pointer_path = writer.paths.ledger_latest_pointer_path
    original = json.loads(pointer_path.read_text(encoding="utf-8"))

    pointer_path.write_text("{", encoding="utf-8")
    with pytest.raises(
        CanonicalLedgerCorruption,
        match="CANONICAL_LATEST_POINTER_INVALID",
    ):
        writer._validate_latest_pointer(events)

    tampered = dict(original)
    tampered["database_promoted"] = True
    pointer_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(
        CanonicalLedgerCorruption,
        match="CANONICAL_LATEST_POINTER_SCHEMA_INVALID",
    ):
        writer._validate_latest_pointer(events)

    tampered = dict(original)
    tampered["ledger_sequence"] = "not-an-int"
    pointer_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(
        CanonicalLedgerCorruption,
        match="CANONICAL_LATEST_POINTER_SEQUENCE_INVALID",
    ):
        writer._validate_latest_pointer(events)

    tampered = dict(original)
    tampered["ledger_prefix_hash"] = "0" * 64
    pointer_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(
        CanonicalLedgerCorruption,
        match="CANONICAL_LATEST_POINTER_MISMATCH",
    ):
        writer._validate_latest_pointer(events)


def test_segment_au_nom_non_canonique_est_refuse(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine", rotate_bytes=1)
    writer.paths.ledger_segments_root.mkdir(parents=True)
    (writer.paths.ledger_segments_root / "alerts.invalid.jsonl").write_text(
        "{}\n",
        encoding="utf-8",
    )

    with pytest.raises(
        CanonicalLedgerCorruption,
        match="CANONICAL_SEGMENT_NAME_INVALID",
    ):
        writer._segment_paths()


def test_rotation_refuse_une_source_partielle(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine", rotate_bytes=1)
    writer.paths.ledger_path.parent.mkdir(parents=True)
    writer.paths.ledger_path.write_bytes(b'{"partial": true}')

    with pytest.raises(
        CanonicalLedgerCorruption,
        match="CANONICAL_LEDGER_ROTATION_SOURCE_INVALID",
    ):
        writer._rotate_ledger_if_needed([])
