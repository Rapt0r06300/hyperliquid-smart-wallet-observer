from __future__ import annotations

from pathlib import Path

from tools.build_codex_execution_status import (
    V21_EVIDENCE,
    V26_EVIDENCE,
    evidence_for,
    parse_work_units,
    render_status,
)


def test_parse_toutes_les_work_units_uniques_de_la_roadmap() -> None:
    root = Path(__file__).resolve().parents[1]
    units = parse_work_units(
        (root / "HYPERSMART_MASTER_ROADMAP.md").read_text(encoding="utf-8")
    )

    assert len(units) == 720
    assert len({unit.identifier for unit in units}) == 720
    assert {"V6-P0-001", "V21-P1-009", "V26-P1-024"}.issubset(
        {unit.identifier for unit in units}
    )


def test_dispositions_rejetees_restent_tracees_sans_reactivation() -> None:
    units = parse_work_units(
        """## V1-P0-001 — Requis

**Status:** `KEEP / P0`.

## V1-P2-002 — Refuse

**Status :** `REJECT_MANDATORY_DEPENDENCY`.
"""
    )

    assert evidence_for(units[0]).state == "PENDING_AUDIT"
    assert evidence_for(units[1]).state == "TRACE_ONLY"


def test_v21_rattache_la_passe_independante_a_ses_preuves() -> None:
    evidence = V21_EVIDENCE["V21-P1-009"]

    assert evidence.state == "VERIFIED"
    assert "64476606" in evidence.commits
    assert "tests/test_economic_proof_audit.py" in evidence.tests
    assert V21_EVIDENCE["V21-P1-010"].state == "VERIFIED"


def test_v26_rattache_le_spine_canonique_a_ses_preuves() -> None:
    evidence = V26_EVIDENCE["V26-P0-001"]

    assert evidence.state == "VERIFIED"
    assert "a1a443f0" in evidence.commits
    assert "tests/test_alert_spine_v26.py" in evidence.tests
    envelope = V26_EVIDENCE["V26-P0-002"]
    assert envelope.state == "VERIFIED"
    assert "28f0154d" in envelope.commits
    assert "tests/test_alert_envelope_v26.py" in envelope.tests
    idempotency = V26_EVIDENCE["V26-P0-003"]
    assert idempotency.state == "VERIFIED"
    assert "b4c46c6c" in idempotency.commits
    assert "tests/test_alert_idempotency_v26.py" in idempotency.tests
    scoring = V26_EVIDENCE["V26-P0-004"]
    assert scoring.state == "VERIFIED"
    assert "425f33c0" in scoring.commits
    assert "tests/test_alert_scoring_v26.py" in scoring.tests
    freshness = V26_EVIDENCE["V26-P0-005"]
    assert freshness.state == "VERIFIED"
    assert "92aa8672" in freshness.commits
    assert "tests/test_alert_freshness_v26.py" in freshness.tests
    parity = V26_EVIDENCE["V26-P0-006"]
    assert parity.state == "VERIFIED"
    assert "8e4a7517" in parity.commits
    assert "tests/test_replacement_parity_v26.py" in parity.tests
    spool = V26_EVIDENCE["V26-P1-001"]
    assert spool.state == "VERIFIED"
    assert "48ff58fe" in spool.commits
    assert "tests/test_alert_spool_v26.py" in spool.tests
    ledger = V26_EVIDENCE["V26-P1-002"]
    assert ledger.state == "VERIFIED"
    assert "a0162181" in ledger.commits
    assert "tests/test_alert_ledger_v26.py" in ledger.tests
    read_model = V26_EVIDENCE["V26-P1-003"]
    assert read_model.state == "VERIFIED"
    assert "0c741184" in read_model.commits
    assert "tests/test_alert_read_model_v26.py" in read_model.tests
    dashboard = V26_EVIDENCE["V26-P1-004"]
    assert dashboard.state == "VERIFIED"
    assert "386a57c5" in dashboard.commits
    assert "d021e502" in dashboard.commits
    assert "tests/test_alert_dashboard_projection_v26.py" in dashboard.tests


def test_rendu_contient_preuve_tests_commit_blocage_et_action() -> None:
    units = parse_work_units("## V1-P0-001 — Exemple\n")
    rendered = render_status(units=units, roadmap_sha256="a" * 64, head="b" * 40)

    assert "| Preuve | Tests | Commits | Blocage | Prochaine action |" in rendered
    assert "PENDING_AUDIT" in rendered
