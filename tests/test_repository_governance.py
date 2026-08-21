from __future__ import annotations

import json
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
    assert "ci-resolved-requirements.txt" in text
    assert "needs: [governance, supply-chain]" in text
    assert "coverage-ratchet" not in text
    assert "python -m coverage run --source=src" not in text
    assert "python tools/check_coverage_ratchet.py" not in text
    assert "hypersmart/security-quality" in text
    assert "SECURITY_QUALITY_GREEN" in text
    assert "hypersmart/technical-perfect" not in text
    assert "continue-on-error" not in text


def test_pre_run_775_est_la_gate_parfaite_principale() -> None:
    text = (ROOT / ".github" / "workflows" / "pre-run-321-775.yml").read_text(encoding="utf-8")
    for marker in (
        "hypersmart/pre-run-775",
        "hypersmart/technical-perfect",
        "python -m pip_audit",
        "python -m ruff check",
        "hypersmart/coverage-parallel-probe",
        "COVERAGE_WITNESS_100_ZERO_MISSING_OK",
        "python tools/check_coverage_ratchet.py",
        "775 + sécurité + qualité + couverture verts",
    ):
        assert marker in text
    assert "python -m coverage run --source=src" not in text


def test_un_seul_workflow_publie_technical_perfect() -> None:
    security = (ROOT / ".github" / "workflows" / "security-quality.yml").read_text(encoding="utf-8")
    pre_run = (ROOT / ".github" / "workflows" / "pre-run-321-775.yml").read_text(encoding="utf-8")
    assert "hypersmart/technical-perfect" not in security
    assert "hypersmart/technical-perfect" in pre_run
    assert "hypersmart/security-quality" in security


def test_technical_perfect_is_not_an_economic_pnl_claim() -> None:
    for workflow_name in ("security-quality.yml", "pre-run-321-775.yml"):
        text = (ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
        for forbidden in ("+4 USD", "PROMOTE"):
            assert forbidden not in text


def test_ci_quality_tools_are_exactly_pinned_and_non_vulnerable() -> None:
    lines = [
        line.strip()
        for line in (ROOT / "requirements-ci-tools.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert lines == [
        "coverage==7.15.2",
        "pip-audit==2.10.1",
        "pytest==9.0.3",
        "pytest-timeout==2.4.0",
        "setuptools==83.0.0",
    ]
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"setuptools>=83.0.0"' in pyproject
    assert '"pytest>=9.0.3,<10"' in pyproject
    assert "pytest>=8,<9" not in pyproject


def test_dependabot_est_interdit_par_le_contrat_main_only() -> None:
    assert not (ROOT / ".github" / "dependabot.yml").exists()
    current = (ROOT / "docs" / "CURRENT_STATE.md").read_text(encoding="utf-8")
    assert "main-only" in current
    assert "sans Dependabot" in current


def test_coverage_ratchet_never_rewrites_the_baseline() -> None:
    text = (ROOT / "tools" / "check_coverage_ratchet.py").read_text(encoding="utf-8")
    assert "couverture_lignes_baseline.json" in text
    assert "write_text" not in text
    assert "COVERAGE_REGRESSION" in text


def test_coverage_target_is_exactly_100_and_zero_missing_lines() -> None:
    baseline = json.loads(
        (ROOT / "tools" / "couverture_lignes_baseline.json").read_text(encoding="utf-8")
    )
    assert float(baseline["min_pct_lignes"]) == 100.0
    assert int(baseline["max_missing_lines"]) == 0

    gate = (ROOT / "tools" / "check_coverage_ratchet.py").read_text(encoding="utf-8")
    assert "missing > max_missing" in gate
    assert "measured + 1e-12 < minimum" in gate

    probe = (ROOT / ".github" / "workflows" / "coverage-parallel-probe.yml").read_text(encoding="utf-8")
    assert 'COVERAGE_SHARDS: "32"' in probe
    assert "python -m coverage run --parallel-mode --source=src" in probe
    assert "--omit" not in probe
    assert "coverage_gap_report.py" in probe
    assert "coverage-gaps.json" in probe
    assert "coverage-gaps.md" in probe
    assert "python tools/check_coverage_ratchet.py" in probe

    pre_run = (ROOT / ".github" / "workflows" / "pre-run-321-775.yml").read_text(encoding="utf-8")
    assert "hypersmart/coverage-parallel-probe" in pre_run
    assert "COVERAGE_WITNESS_100_ZERO_MISSING_OK" in pre_run


def test_coverage_probe_has_git_parent_for_anti_deletion_proof() -> None:
    text = (ROOT / ".github" / "workflows" / "coverage-parallel-probe.yml").read_text(encoding="utf-8")
    assert "fetch-depth: 2" in text
    assert "COVERAGE_ARTIFACT_COUNT_INVALID" in text
    assert "test \"${#COVERAGE_FILES[@]}\" -eq 32" in text


def test_current_state_supersedes_stale_master_document() -> None:
    current = (ROOT / "docs" / "CURRENT_STATE.md").read_text(encoding="utf-8")
    gateway = (ROOT / "docs" / "ETAT_ET_FEUILLE_DE_ROUTE.md").read_text(encoding="utf-8")
    assert "775/775" in current
    assert "Aucune cible économique" in current
    assert "hypersmart/technical-perfect" in current
    assert "hypersmart/security-quality" in current
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
