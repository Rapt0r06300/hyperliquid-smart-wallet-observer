from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from hl_observer.alerts.spine import (
    AlertSpinePaths,
    CanonicalAlertWriter,
    CanonicalLedgerCorruption,
    build_alert_proposal,
)


def _proposal(sequence: int) -> dict[str, object]:
    return build_alert_proposal(
        producer_id="rebuild-producer",
        producer_epoch="rebuild-epoch-1",
        producer_seq=sequence,
        source_id="rebuild-source",
        source_uri=f"https://example.invalid/rebuild/{sequence}",
        source_content_hash=hashlib.sha256(str(sequence).encode()).hexdigest(),
        observed_at_ms=1_000 + sequence,
        fetched_at_ms=2_000 + sequence,
        verified_at_ms=3_000 + sequence,
        category="MARKET_EVENT",
        headline=f"Rebuild alert {sequence}",
        dedup_key=f"rebuild:{sequence}",
        policy_version="alert-rebuild-test.v1",
        ingestion_code_sha="e" * 40,
        entity_ids=[f"asset:{sequence}"],
        source_health_state="HEALTHY",
        freshness_state="FRESH",
        payload={"alert_family": "integrity", "sequence": sequence},
    )


def _writer(root: Path) -> CanonicalAlertWriter:
    return CanonicalAlertWriter(
        AlertSpinePaths.from_root(root),
        clock_ms=lambda: 50_000,
        ledger_rotate_bytes=1,
        projection_limit=2,
    )


def _seed(writer: CanonicalAlertWriter) -> None:
    producer = writer.producer("rebuild-producer")
    for sequence in range(4):
        producer.submit(_proposal(sequence))
    writer.process_pending()


def _file_manifest(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _crash_after_projection_delete(projection_root: Path, allowed_root: Path) -> int:
    script = """
import os
import shutil
import sys
from pathlib import Path

target = Path(sys.argv[1]).resolve()
allowed = Path(sys.argv[2]).resolve()
if not target.is_relative_to(allowed) or target.name != "projections":
    raise SystemExit(96)
shutil.rmtree(target)
os._exit(91)
"""
    process = subprocess.run(
        [sys.executable, "-c", script, str(projection_root), str(allowed_root)],
        check=False,
    )
    return process.returncode


def test_reconstruction_exacte_apres_suppression_et_crash_processus(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    root = tmp_path_factory.mktemp("pr") / "spine"
    writer = _writer(root)
    _seed(writer)
    baseline = writer.rebuild_projection(displayed_at_ms=50_100)
    baseline_bytes = writer.paths.projection_path.read_bytes()
    canonical_root = writer.paths.ledger_path.parent
    canonical_before = _file_manifest(canonical_root)

    returncode = _crash_after_projection_delete(
        writer.paths.projection_path.parent,
        writer.paths.root,
    )

    assert returncode == 91
    assert not writer.paths.projection_path.parent.exists()
    assert _file_manifest(canonical_root) == canonical_before

    restarted = _writer(root)
    rebuilt = restarted.rebuild_projection(displayed_at_ms=50_100)

    assert rebuilt == baseline
    assert restarted.paths.projection_path.read_bytes() == baseline_bytes
    assert rebuilt["returned_alert_count"] == 2
    assert rebuilt["omitted_alert_count"] == 2
    assert _file_manifest(canonical_root) == canonical_before
    cursor = json.loads(
        restarted.paths.projection_cursor_path.read_text(encoding="utf-8")
    )
    assert cursor["ledger_sequence"] == 4
    assert cursor["paper_read_only"] is True
    assert cursor["real_execution"] is False


def test_reconstruction_refuse_ledger_corrompu_sans_publier_de_projection(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    root = tmp_path_factory.mktemp("pc") / "spine"
    writer = _writer(root)
    _seed(writer)
    projection_root = writer.paths.projection_path.parent.resolve()
    assert projection_root.is_relative_to(root.resolve())
    shutil.rmtree(projection_root)
    segment = next(writer.paths.ledger_segments_root.glob("*.jsonl"))
    segment.write_bytes(segment.read_bytes() + b" ")

    with pytest.raises(
        CanonicalLedgerCorruption,
        match="CANONICAL_SEGMENT_CHECKSUM_MISMATCH",
    ):
        _writer(root).rebuild_projection(displayed_at_ms=50_100)

    assert not writer.paths.projection_path.exists()
    assert not writer.paths.projection_cursor_path.exists()
