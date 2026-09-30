from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "hypersmart-runner-smoke-final-v1.yml"


def _workflow() -> str:
    assert WORKFLOW.is_file()
    return WORKFLOW.read_text(encoding="utf-8", errors="replace")


def test_historical_runner_smoke_is_a_manual_inert_tombstone() -> None:
    text = _workflow()
    preamble = text.split("jobs:", 1)[0]
    assert "workflow_dispatch:" in preamble
    assert "push:" not in preamble
    assert "schedule:" not in preamble
    assert "runs-on: ubuntu-latest" in text
    assert "self-hosted" not in text.lower()
    assert "exit 1" in text
    assert "GitHub-hosted Alina SmartFlow workflows" in text


def test_historical_runner_smoke_cannot_execute_or_touch_a_user_pc() -> None:
    text = _workflow().lower()
    for forbidden in (
        "c:\\users\\",
        "self-hosted",
        "alina_python_exe",
        "hyperSmart-runner-data".lower(),
        "runpy.run_module",
        "powershell -nologo",
    ):
        assert forbidden not in text
