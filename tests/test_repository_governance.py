from __future__ import annotations

from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def _workflows() -> dict[str, str]:
    root = ROOT / ".github" / "workflows"
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(root.glob("*.yml"))}


def test_main_only_est_un_contrat_versionne() -> None:
    state = (ROOT / "docs" / "CURRENT_STATE.md").read_text(encoding="utf-8")
    assert "main-only" in state
    assert "branches agents/ interdites" in state
    assert "sans Dependabot" in state


def test_workflows_ne_declenchent_pas_sur_pull_request() -> None:
    offenders: list[str] = []
    for name, text in _workflows().items():
        if re.search(r"(?m)^\s*pull_request(?:_target)?\s*:", text):
            offenders.append(name)
    assert not offenders, "Workflows PR interdits par le contrat main-only: " + ", ".join(offenders)


def test_workflows_self_hosted_restent_derriere_go_gate() -> None:
    offenders: list[str] = []
    for name, text in _workflows().items():
        if "self-hosted" not in text:
            continue
        if "GO_SELF_HOSTED" not in text and "self_hosted_go_gate" not in text:
            offenders.append(name)
    assert not offenders, "Self-hosted sans gate explicite: " + ", ".join(offenders)


def test_manifeste_775_reste_honnete_et_versionne() -> None:
    path = ROOT / "docs" / "PRE_RUN_775_CANONICAL_STATUS.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["canonical_total"] == 775
    assert data["technical_done"] == 775
    assert data["economic_completion_claimed"] is False


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
