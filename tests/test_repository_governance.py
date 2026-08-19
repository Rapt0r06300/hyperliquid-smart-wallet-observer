from __future__ import annotations

from pathlib import Path

from check_repo_governance import local_failures

ROOT = Path(__file__).resolve().parents[1]


def test_repository_governance_files_are_complete() -> None:
    assert local_failures() == []


def test_security_quality_workflow_is_fail_closed() -> None:
    text = (ROOT / ".github" / "workflows" / "security-quality.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in text
    assert "persist-credentials: false" in text
    assert "--require-protected-main" in text
    assert "pip-audit==2.10.1" in text
    assert "python -m pip_audit" in text
    assert "python -m coverage run --source=src" in text
    assert "python tools/check_coverage_ratchet.py" in text
    assert "continue-on-error" not in text


def test_coverage_ratchet_never_rewrites_the_baseline() -> None:
    text = (ROOT / "tools" / "check_coverage_ratchet.py").read_text(encoding="utf-8")
    assert "couverture_lignes_baseline.json" in text
    assert "write_text" not in text
    assert "COVERAGE_REGRESSION" in text


def test_current_state_supersedes_stale_master_document() -> None:
    current = (ROOT / "docs" / "CURRENT_STATE.md").read_text(encoding="utf-8")
    gateway = (ROOT / "docs" / "ETAT_ET_FEUILLE_DE_ROUTE.md").read_text(encoding="utf-8")
    assert "775/775" in current
    assert "Aucune cible économique" in current
    assert "CURRENT_STATE.md" in gateway
    assert "Source de vérité actuelle" in gateway
