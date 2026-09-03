from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from hl_observer.alerts.coverage import load_source_coverage_universe

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "config" / "alerts" / "source_coverage_universe.json"
SCRIPT = ROOT / "tools" / "check_source_coverage.py"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--universe", str(UNIVERSE), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_cli_publie_recu_et_attestation_sans_inventer_de_connexion(tmp_path: Path) -> None:
    destination = tmp_path / "coverage.json"
    before_ms = time.time_ns() // 1_000_000
    result = _run("--output", str(destination))
    after_ms = time.time_ns() // 1_000_000

    assert result.returncode == 0, result.stderr
    report = json.loads(destination.read_text(encoding="utf-8"))
    assert report["schema_version"] == "hypersmart.source_coverage_report.v1"
    receipt = report["coverage_receipt"]
    attestation = report["completeness_attestation"]
    assert before_ms <= receipt["evaluated_at_ms"] <= after_ms
    assert attestation["evaluated_at_ms"] == receipt["evaluated_at_ms"]
    assert receipt["counts"]["actually_connected_sources"] == 0
    assert attestation["coverage_state"] == "COVERAGE_UNKNOWN"
    assert attestation["source_coverage_receipt_hash"] == receipt["receipt_hash"]
    assert "operational=BLOCKED" in result.stdout


def test_cli_conserve_declaration_non_prouvee_avec_replay_identique(tmp_path: Path) -> None:
    allocation = tmp_path / "allocation.json"
    allocation.write_text(json.dumps({"SEC_FILINGS": 100}), encoding="utf-8")
    evidence = tmp_path / "evidence.json"
    evidence.write_text(
        json.dumps(
            {
                "kind": "MEASURED_RECALL_PROXY",
                "universe_hash": load_source_coverage_universe(UNIVERSE)["universe_hash"],
                "measured_at_ms": 9_000,
                "valid_for_ms": 5_000,
                "method": "Pre-registered labelled sample",
                "sample_definition": "100 frozen relevant events",
                "relevant_events": 100,
                "detected_events": 83,
                "evidence_refs": ["fixture:events-v1"],
            }
        ),
        encoding="utf-8",
    )
    before_inputs = allocation.read_bytes(), evidence.read_bytes()
    output = tmp_path / "result.json"
    args = (
        "--output", str(output), "--evaluated-at-ms", "10000",
        "--allocation", str(allocation), "--completeness-evidence", str(evidence),
    )
    first = _run(*args)
    assert first.returncode == 0, first.stderr
    first_bytes = output.read_bytes()
    second = _run(*args)
    assert second.returncode == 0, second.stderr
    assert output.read_bytes() == first_bytes
    assert before_inputs == (allocation.read_bytes(), evidence.read_bytes())
    report = json.loads(first_bytes)
    attestation = report["completeness_attestation"]
    assert attestation["allocation"]["total_percent"] == 100.0
    assert attestation["completeness_evidence"]["reported_recall"] == 0.83
    assert attestation["empirical_evidence_available"] is False
    assert attestation["completeness_claimed"] is False
    assert "completeness=COVERAGE_UNKNOWN" in first.stdout


def test_cli_ne_publie_pas_de_rapport_sur_preuve_invalide(tmp_path: Path) -> None:
    evidence = tmp_path / "invalid.json"
    evidence.write_text("{}", encoding="utf-8")
    output = tmp_path / "result.json"
    result = _run("--completeness-evidence", str(evidence), "--output", str(output))

    assert result.returncode == 2
    assert "SOURCE_COVERAGE_INVALID" in result.stdout
    assert not output.exists()


def test_cli_refuse_de_remplacer_une_entree_par_le_rapport(tmp_path: Path) -> None:
    allocation = tmp_path / "allocation.json"
    original = b'{"SEC_FILINGS": 100}'
    allocation.write_bytes(original)
    result = _run("--allocation", str(allocation), "--output", str(allocation))

    assert result.returncode == 2
    assert "OUTPUT_OVERWRITES_INPUT" in result.stdout
    assert allocation.read_bytes() == original
