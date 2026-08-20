from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "hypersmart-runner-smoke-final-v1.yml"


def _workflow() -> str:
    assert WORKFLOW.is_file()
    return WORKFLOW.read_text(encoding="utf-8", errors="replace")


def test_smoke_uses_only_the_dedicated_runner_and_manual_fallback() -> None:
    text = _workflow()
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "push:" not in text
    assert "runs-on: [self-hosted, Windows, X64, hypersmart-final-v1]" in text
    assert "github.actor == 'Rapt0r06300'" in text
    assert "github.ref == 'refs/heads/main'" in text
    assert "github.event.repository.fork == false" in text


def test_smoke_is_exact_sha_paper_only_and_has_no_command_input() -> None:
    text = _workflow()
    assert "expected_sha:" in text
    assert "SMOKE_STALE_MAIN_REFUSED" in text
    assert "SMOKE_EXACT_CHECKOUT_IMPORT_REFUSED" in text
    assert "control/alina_final_jobs/" in text
    assert "SMOKE_ARBITRARY_FIELD_REFUSED" in text
    assert "shell:" not in text.split("inputs:", 1)[1].split("permissions:", 1)[0]
    assert "command:" not in text.split("inputs:", 1)[1].split("permissions:", 1)[0]
    for marker in (
        "HL_ENABLE_MAINNET_EXECUTION: '0'",
        "HL_ENABLE_TESTNET_EXECUTION: '0'",
        "REAL_MAINNET_TRADING: 'false'",
        "TESTNET_EXECUTION_ENABLED: 'false'",
        "HYPERSMART_ENABLE_REAL_ORDERS: '0'",
        "ENABLE_REAL_ORDERS: '0'",
        "HYPERSMART_ANALYSIS_LOCAL_ONLY: '1'",
    ):
        assert marker in text


def test_smoke_publishes_only_a_compact_fixed_proof() -> None:
    text = _workflow()
    assert "HYPERSMART_RUNNER_SMOKE_PROOF.json" in text
    assert "hypersmart.runner_smoke_proof.v1" in text
    assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in text
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in text
    assert "GITHUB_PC_GITHUB_SMOKE_OK" in text
    assert "real_execution = $false" in text
    assert "arbitrary_command = $false" in text


def test_smoke_uses_a_valid_local_python_and_exact_checkout_import() -> None:
    text = _workflow()
    assert "ALINA_PYTHON_EXE" in text
    assert r"C:\HyperSmart-Runner-Data\runtime\python\Scripts\python.exe" in text
    assert r"portable_runtime\python\python.exe" in text
    assert r"tools\python\python.exe" in text
    assert "Get-Command python -ErrorAction SilentlyContinue" in text
    assert "import sys, pydantic" in text
    assert "SMOKE_PYTHON_REFUSED" in text
    assert "SMOKE_PYTHON_OK" in text
    assert "SMOKE_EXACT_CHECKOUT_IMPORT_REFUSED" in text


def test_smoke_bypasses_only_the_actions_temporary_script_policy() -> None:
    text = _workflow()
    shell = "shell: powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File {0}"
    assert text.count(shell) == 3
    assert "shell: powershell\n" not in text
