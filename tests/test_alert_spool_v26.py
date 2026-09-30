from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from hl_observer.alerts.spine import (
    PROPOSAL_SCHEMA,
    AlertSpinePaths,
    AlertValidationError,
    CanonicalAlertWriter,
    build_alert_proposal,
)


def _hash_payload(payload: dict[str, object]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _proposal(producer_id: str, sequence: int) -> dict[str, object]:
    return build_alert_proposal(
        producer_id=producer_id,
        producer_epoch="epoch-restartable-1",
        producer_seq=sequence,
        source_id=f"source-{producer_id}",
        source_uri=f"https://example.invalid/{producer_id}/{sequence}",
        source_content_hash=hashlib.sha256(
            f"{producer_id}:{sequence}".encode()
        ).hexdigest(),
        observed_at_ms=1_000 + sequence,
        fetched_at_ms=2_000 + sequence,
        verified_at_ms=3_000 + sequence,
        category="MARKET_EVENT",
        headline=f"Alert {producer_id} {sequence}",
        dedup_key=f"{producer_id}:{sequence}",
        policy_version="alerts-spool-test.v1",
        ingestion_code_sha="a" * 40,
        source_health_state="HEALTHY",
        freshness_state="FRESH",
        payload={"producer": producer_id, "sequence": sequence},
    )


def _writer(root: Path) -> CanonicalAlertWriter:
    return CanonicalAlertWriter(
        AlertSpinePaths.from_root(root),
        clock_ms=lambda: 10_000,
    )


def test_spool_expose_schema_epoch_sequence_et_hash_payload(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine")
    proposal = _proposal("producer-a", 7)

    pending = writer.producer("producer-a").submit(proposal)
    stored = json.loads(pending.read_text(encoding="utf-8"))

    assert stored["schema_version"] == PROPOSAL_SCHEMA
    assert stored["producer_epoch"] == "epoch-restartable-1"
    assert stored["producer_seq"] == 7
    assert stored["payload_hash"] == _hash_payload(stored["payload"])
    assert not list(pending.parent.glob("*.tmp"))


def test_spool_refuse_un_payload_modifie_apres_publication(tmp_path: Path) -> None:
    writer = _writer(tmp_path / "spine")
    pending = writer.producer("producer-a").submit(_proposal("producer-a", 1))
    stored = json.loads(pending.read_text(encoding="utf-8"))
    stored["payload"]["sequence"] = 999
    pending.write_text(json.dumps(stored), encoding="utf-8")

    with pytest.raises(AlertValidationError, match="PAYLOAD_HASH_MISMATCH"):
        writer.process_pending()


def test_temporaire_abandonne_ne_bloque_pas_un_autre_producteur(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path / "spine")
    dead_directory = writer.paths.pending_root / "producer-dead"
    dead_directory.mkdir(parents=True)
    (dead_directory / ".proposal-interrompue.tmp").write_bytes(b'{"partial":')
    writer.producer("producer-live").submit(_proposal("producer-live", 1))

    receipt = writer.process_pending()

    assert receipt["accepted"] == 1
    assert writer.read_ledger()[0]["producer_id"] == "producer-live"
    assert (dead_directory / ".proposal-interrompue.tmp").is_file()


def test_reprise_identique_ne_recrit_aucune_archive_producteur(
    tmp_path: Path,
) -> None:
    writer = _writer(tmp_path / "spine")
    proposal_a = _proposal("producer-a", 1)
    writer.producer("producer-a").submit(proposal_a)
    writer.producer("producer-b").submit(_proposal("producer-b", 1))
    writer.process_pending()
    archive_a = next((writer.paths.acknowledged_root / "producer-a").glob("*.json"))
    archive_b = next((writer.paths.acknowledged_root / "producer-b").glob("*.json"))
    before_a = (archive_a.read_bytes(), archive_a.stat().st_mtime_ns)
    before_b = (archive_b.read_bytes(), archive_b.stat().st_mtime_ns)

    writer.producer("producer-a").submit(proposal_a)
    receipt = writer.process_pending()

    assert receipt["accepted"] == 0
    assert receipt["deduplicated"] == 1
    assert (archive_a.read_bytes(), archive_a.stat().st_mtime_ns) == before_a
    assert (archive_b.read_bytes(), archive_b.stat().st_mtime_ns) == before_b


def test_producteur_tue_apres_publication_est_rejoue_sans_perte(
    tmp_path: Path,
) -> None:
    root = tmp_path / "spine"
    marker = root / "published.ready"
    script = "\n".join(
        (
            "import hashlib, sys, time",
            "from pathlib import Path",
            "from hl_observer.alerts.spine import AlertSpinePaths, CanonicalAlertWriter, build_alert_proposal",
            "root = Path(sys.argv[1])",
            "writer = CanonicalAlertWriter(AlertSpinePaths.from_root(root))",
            "proposal = build_alert_proposal(producer_id='producer-child', producer_epoch='epoch-child-1', producer_seq=1, source_id='source-child', source_uri='https://example.invalid/child', source_content_hash=hashlib.sha256(b'child').hexdigest(), observed_at_ms=1000, fetched_at_ms=2000, verified_at_ms=3000, category='MARKET_EVENT', headline='Child alert', dedup_key='child:1', policy_version='alerts-spool-test.v1', ingestion_code_sha='a' * 40, source_health_state='HEALTHY', freshness_state='FRESH', payload={'child': True})",
            "writer.producer('producer-child').submit(proposal)",
            "(root / 'published.ready').write_text('published', encoding='ascii')",
            "time.sleep(60)",
        )
    )
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(root)],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.is_file() and process.poll() is None:
            if time.monotonic() >= deadline:
                pytest.fail("Le producteur enfant n'a pas publie dans le delai")
            time.sleep(0.05)
        if not marker.is_file():
            _, stderr = process.communicate(timeout=2)
            pytest.fail(f"Le producteur enfant a echoue: {stderr}")
        process.kill()
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=10)

    writer = _writer(root)
    receipt = writer.process_pending()

    assert receipt["accepted"] == 1
    assert receipt["ledger_count"] == 1
    assert writer.read_ledger()[0]["producer_id"] == "producer-child"
