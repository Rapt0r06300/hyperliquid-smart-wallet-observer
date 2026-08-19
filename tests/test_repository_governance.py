from __future__ import annotations

from pathlib import Path

from check_repo_governance import local_failures

ROOT = Path(__file__).resolve().parents[1]


def test_repository_governance_files_are_complete() -> None:
    assert local_failures() == []


def test_security_quality_workflow_is_fail_closed() -> None:
    text = (ROOT / ".github" / "workflows" / "security-quality.yml").read_text(encoding="utf-8")
    assert "contents: read" in text
    assert "statuses: write" in text
    assert "persist-credentials: false" in text
    assert "requirements-ci-tools.txt" in text
    assert "python -m pip_audit" in text
    assert "python -m coverage run --source=src" in text
    assert "python tools/check_coverage_ratchet.py" in text
    assert "ci-resolved-requirements.txt" in text
    assert "needs: [governance, supply-chain, coverage-ratchet]" in text
    assert "hypersmart/technical-perfect" in text
    assert "TECHNICAL_PERFECT_GREEN" in text
    assert "continue-on-error" not in text


def test_technical_perfect_is_not_an_economic_pnl_claim() -> None:
    text = (ROOT / ".github" / "workflows" / "security-quality.yml").read_text(encoding="utf-8")
    block = text.split("technical-perfect:", 1)[1]
    for forbidden in ("+4 USD", "LIQUIDATABLE_NET", "MORE_DATA", "PROMOTE"):
        assert forbidden not in block


def test_ci_quality_tools_are_exactly_pinned() -> None:
    lines = [
        line.strip()
        for line in (ROOT / "requirements-ci-tools.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert lines == ["coverage==7.15.2", "pip-audit==2.10.1"]


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
    assert "hypersmart/technical-perfect" in current
    assert "indépendante du verdict économique" in current
    assert "CURRENT_STATE.md" in gateway
    assert "Source de vérité actuelle" in gateway


def test_generated_local_artifacts_do_not_reenter_the_source_tree() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in (
        "/logs-audit/",
        "/moisson_console.txt",
        "/runtime/audit/*.txt",
        "/runtime/rapports/**/*.txt",
    ):
        assert pattern in gitignore

    for relative in (
        "moisson_console.txt",
        "logs-audit/derniers_echecs.json",
        "logs-audit/recaps/RECAP-20260722-134021.md",
        "logs-audit/recaps/RECAP-20260722-135031.md",
        "runtime/audit/echecs_pytest.txt",
        "runtime/audit/test_edge.txt",
        "runtime/rapports/checkpoint_oos_shadow/diag_planif.txt",
    ):
        assert not (ROOT / relative).exists(), relative
