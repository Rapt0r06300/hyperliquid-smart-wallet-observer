"""The former final-v1 PC runner is retained only as a disabled tombstone."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "alina-self-hosted-final-v1.yml"


def test_final_v1_self_hosted_workflow_is_unreachable() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "if: ${{ false }}" in text
    assert "runs-on: ubuntu-latest" in text
    assert "self-hosted runner" in text
    assert "exit 1" in text
    assert "runs-on: [self-hosted" not in text


def test_final_v1_has_no_triggered_pc_or_execution_path() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in text
    assert "schedule:" not in text
    assert "repository_dispatch:" not in text
    assert "workflow_run:" not in text
    assert "git push" not in text
    assert "/exchange" not in text


def test_final_v1_points_operators_to_github_hosted_path() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "GitHub-hosted Alina SmartFlow workflows" in text
    assert "Dataset V2 contracts" in text
