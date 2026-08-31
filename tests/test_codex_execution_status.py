from __future__ import annotations

from pathlib import Path

from tools.build_codex_execution_status import (
    V21_EVIDENCE,
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


def test_v21_ne_masque_pas_la_passe_independante_encore_en_cours() -> None:
    assert V21_EVIDENCE["V21-P1-009"].state == "IN_PROGRESS"
    assert V21_EVIDENCE["V21-P1-010"].state == "VERIFIED"


def test_rendu_contient_preuve_tests_commit_blocage_et_action() -> None:
    units = parse_work_units("## V1-P0-001 — Exemple\n")
    rendered = render_status(units=units, roadmap_sha256="a" * 64, head="b" * 40)

    assert "| Preuve | Tests | Commits | Blocage | Prochaine action |" in rendered
    assert "PENDING_AUDIT" in rendered
