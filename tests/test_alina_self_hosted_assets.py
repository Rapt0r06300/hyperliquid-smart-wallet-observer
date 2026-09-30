"""Regression contract: historical self-hosted surfaces stay unreachable."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "alina-self-hosted.yml"


def test_legacy_self_hosted_workflow_is_permanently_disabled() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "if: ${{ false }}" in text
    assert "runs-on: ubuntu-latest" in text
    assert "runs-on: [self-hosted" not in text
    assert "Disabled permanently" in text
    assert "exit 1" in text


def test_legacy_self_hosted_workflow_cannot_mutate_repository() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in text
    assert "contents: write" not in text
    assert "git push" not in text
    assert "schedule:" not in text


def test_obsolete_pc_installers_are_not_canonical_workflow_dependencies() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    forbidden = (
        "INSTALLER_ALINA_RUNNER",
        "VERIFIER_ALINA_RUNNER",
        "CONTROLER_ALINA_RUNNER",
        "ALINA_PYTHON_EXE",
    )
    assert all(marker not in text for marker in forbidden)
