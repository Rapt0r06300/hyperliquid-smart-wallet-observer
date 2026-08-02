from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "portable-release-windows.yml"
TEXT = WORKFLOW.read_text(encoding="utf-8")


def test_windows_release_builds_embedded_runtime_without_setup_python():
    assert "runs-on: windows-latest" in TEXT
    assert "tools\\install_portable_runtime.ps1" in TEXT
    assert "tools\\python\\python.exe" in TEXT
    assert "actions/setup-python" not in TEXT
    assert "wheelhouse_lock.py" in TEXT
    assert "WHEELHOUSE_LOCK.json" in TEXT


def test_final_cmd_is_the_release_entrypoint_and_uses_external_output():
    assert "CREER_ARCHIVE_PORTABLE.cmd --sortie-dir" in TEXT
    assert "RUNNER_TEMP" in TEXT
    assert "RELEASE_REPORT.json" in TEXT
    assert "PORTABLE_VALIDATION.json" in TEXT
    assert "RELEASE_READY is not true" in TEXT


def test_publish_and_attestation_are_after_validation():
    validate = TEXT.index("Build twice and validate the extracted ZIP")
    attest = TEXT.index("Attest ZIP and SBOM provenance")
    publish = TEXT.index("Publish verified portable release")
    assert validate < attest < publish
    assert "actions/attest-build-provenance@v2" in TEXT
    assert "actions/upload-artifact@v4" in TEXT
    assert "SBOM.cyclonedx.json" in TEXT


def test_ci_is_paper_read_only_and_exact_head():
    assert 'HL_ENABLE_MAINNET_EXECUTION: "0"' in TEXT
    assert 'HL_ENABLE_TESTNET_EXECUTION: "0"' in TEXT
    assert 'REAL_MAINNET_TRADING: "false"' in TEXT
    assert 'TESTNET_EXECUTION_ENABLED: "false"' in TEXT
    assert "GITHUB_SHA" in TEXT
    assert "git status --porcelain" in TEXT
    assert "real_execution" in TEXT


def test_writer_registry_is_explicit_and_empty():
    assert "lanceur_pids.json" in TEXT
    assert '{\"composants\":{},\"collecteurs\":{}}' in TEXT
    assert "System.Text.UTF8Encoding($false)" in TEXT
    writer_step = TEXT[TEXT.index("Materialize fail-closed writer proof"):]
    assert "Set-Content" not in writer_step.split("- name:", 1)[0]
