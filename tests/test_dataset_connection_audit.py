from __future__ import annotations

import json
from pathlib import Path

from hl_observer.datasets.connection_audit import (
    build_connection_audit,
    write_connection_audit,
)


def _mark(root: Path) -> None:
    path = root / "runtime" / "reports" / "datasets" / "SELECTION_PROVENANCE.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "source_release_id": 371149058,
                "selection_digest": "a" * 64,
                "paper_read_only": True,
                "real_execution": False,
            }
        ),
        encoding="utf-8",
    )


def _write(root: Path, relative: str, content: bytes = b"{}\n") -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def test_audit_raccordement_distingue_cablage_et_preuves_de_run(tmp_path: Path) -> None:
    _mark(tmp_path)
    _write(tmp_path, "runtime/data/vault_fills.jsonl")
    _write(tmp_path, "runtime/data/bbo_tape.jsonl")
    _write(tmp_path, "runtime/data/carnet_venues.jsonl")
    _write(tmp_path, "data/hl_observer.sqlite3", b"sqlite-placeholder")
    _write(tmp_path, "runtime/research_lab/run-a/episodes.jsonl")

    payload = build_connection_audit(tmp_path)

    assert payload["wiring_status"] == "CONNECTED"
    assert payload["all_available_groups_have_consumer"] is True
    assert payload["run_evidence_status"] == "PENDING_RUNS"
    assert set(payload["pending_run_evidence_groups"]) == {
        "copy_vault",
        "lead_lag",
        "cross_venue",
        "sqlite",
        "research_lab",
    }
    assert payload["groups"]["copy_vault"]["consumer_known"] is True
    assert payload["groups"]["sqlite"]["state"] == "WIRED_AWAITING_SQLITE_SCAN"


def test_audit_devient_complet_quand_les_rapports_de_consommation_existent(tmp_path: Path) -> None:
    _mark(tmp_path)
    _write(tmp_path, "runtime/data/vault_fills.jsonl")
    _write(tmp_path, "runtime/data/bbo_tape.jsonl")
    _write(tmp_path, "runtime/data/carnet_venues.jsonl")
    _write(tmp_path, "data/hl_observer.sqlite3", b"sqlite-placeholder")
    _write(tmp_path, "runtime/research_lab/run-a/episodes.jsonl")
    reports = tmp_path / "runtime" / "reports" / "datasets"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "SOURCE_CONSUMPTION_COVERAGE.json").write_text(
        json.dumps(
            {
                "families": {
                    "copy_vault": {"status": "FULL"},
                    "lead_lag": {"status": "FULL"},
                    "cross_venue": {"status": "FULL"},
                }
            }
        ),
        encoding="utf-8",
    )
    (reports / "SQLITE_INVENTORY.json").write_text(
        json.dumps({"readable_database_count": 1}), encoding="utf-8"
    )
    (reports / "SQLITE_RESEARCH_CATALOG.json").write_text(
        json.dumps({"table_sources": {"fills": ["db"]}}), encoding="utf-8"
    )
    (reports / "RESEARCH_LAB_STREAM_PROFILE.json").write_text(
        json.dumps(
            {
                "scanned_gib": 1.25,
                "complete_file_count": 1,
                "partial_file_count": 0,
            }
        ),
        encoding="utf-8",
    )

    payload = build_connection_audit(tmp_path)

    assert payload["wiring_status"] == "CONNECTED"
    assert payload["run_evidence_status"] == "COMPLETE_FOR_AVAILABLE_SOURCES"
    assert payload["pending_run_evidence_groups"] == []
    assert payload["groups"]["sqlite"]["state"] == "RUN_EVIDENCE_READY"
    assert payload["groups"]["research_lab"]["scanned_gib"] == 1.25


def test_audit_refuse_de_declarer_connected_sans_provenance_release(tmp_path: Path) -> None:
    _write(tmp_path, "runtime/data/bbo_tape.jsonl")

    payload = build_connection_audit(tmp_path)

    assert payload["provenance_ok"] is False
    assert payload["wiring_status"] == "NO_PROVENANCE"


def test_audit_ecrit_json_et_markdown_sans_pretendre_un_edge(tmp_path: Path) -> None:
    _mark(tmp_path)
    _write(tmp_path, "runtime/data/bbo_tape.jsonl")

    json_path, md_path, payload = write_connection_audit(tmp_path)

    assert json_path.is_file()
    assert md_path.is_file()
    assert payload["paper_read_only"] is True
    text = md_path.read_text(encoding="utf-8")
    assert "CONNECTED" in text
    assert "ne signifie pas qu'un edge est rentable" in text
