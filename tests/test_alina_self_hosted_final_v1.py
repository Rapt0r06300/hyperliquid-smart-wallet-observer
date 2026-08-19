from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "alina-self-hosted-final-v1.yml"
INSTALLER = ROOT / "tools" / "INSTALLER_ALINA_RUNNER_FINAL_V1.ps1"
INSTALLER_LAUNCHER = ROOT / "INSTALLER_ALINA_RUNNER_FINAL_V1.cmd"
CONTROL_README = ROOT / "control" / "alina_final_jobs" / "README.md"


def _text(path: Path) -> str:
    assert path.is_file(), str(path)
    return path.read_text(encoding="utf-8", errors="replace")


def test_final_workflow_isolated_from_legacy_queue() -> None:
    text = _text(WORKFLOW)
    assert "control/alina_final_jobs/*.json" in text
    assert "runs-on: [self-hosted, Windows, X64, hypersmart-final-v1]" in text
    assert "runs-on: [self-hosted, Windows, X64, hypersmart]" not in text
    assert "SELF_HOSTED_STALE_SHA_REFUSED" in text
    assert "commits/main" in text
    assert "FINAL_CONTROL_ONLY_COMMIT_REQUIRED" in text
    assert "pull_request:" not in text
    assert "cancel-in-progress: false" in text


def test_final_workflow_requires_exact_technical_green_before_compute() -> None:
    text = _text(WORKFLOW)
    assert "TECHNICAL_STATUS_NOT_GREEN" in text
    for context in (
        "hypersmart/pre-run-775",
        "hypersmart/technical-perfect",
        "hypersmart/security-quality",
    ):
        assert context in text
    gate = text.index("Exiger les certifications techniques vertes du SHA exact")
    compute = text.index("Lancer le calcul final paper read-only")
    assert gate < compute


def test_final_workflow_is_paper_only_and_has_minimal_write_permission() -> None:
    text = _text(WORKFLOW)
    assert "permissions:\n  contents: read\n  statuses: write" in text
    assert "contents: write" not in text
    assert "pull-requests: write" not in text
    for marker in (
        "HL_ENABLE_MAINNET_EXECUTION: '0'",
        "HL_ENABLE_TESTNET_EXECUTION: '0'",
        "REAL_MAINNET_TRADING: 'false'",
        "HYPERSMART_ENABLE_REAL_ORDERS: '0'",
        "ENABLE_REAL_ORDERS: '0'",
    ):
        assert marker in text
    assert "persist-credentials: false" in text
    assert "git push" not in text


def test_final_workflow_publishes_honest_three_of_three_status() -> None:
    text = _text(WORKFLOW)
    assert "hl_observer.ops.self_hosted_return" in text
    assert "economic_certification.all_families_certified" in text
    assert "hypersmart/economic-3of3" in text
    assert "ECONOMIC_3OF3_NOT_CERTIFIED" in text
    assert "3/3 families separately certified >=4 USD net" in text
    assert "GITHUB_SAFE_FINAL_PROOF.json" in text
    assert "raw_data_uploaded = $false" in text
    assert "local_paths_uploaded = $false" in text


def test_final_workflow_upload_is_allowlisted_and_actions_are_pinned() -> None:
    text = _text(WORKFLOW)
    assert "github_public" in text
    assert "path: ${{ steps.compact_return.outputs.public_dir }}" in text
    assert "actions/checkout@11d5960a326750d5838078e36cf38b85af677262" in text
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in text
    upload = text.split("Remonter uniquement le retour public final allowlisté", 1)[1]
    assert "datasets\\assets" not in upload.split("Publier le verdict économique", 1)[0]


def test_final_installer_uses_unique_root_name_and_label() -> None:
    text = _text(INSTALLER)
    assert "GO_SELF_HOSTED" in text
    assert "ALINA_RUNNER_HYPERSMART_FINAL_V1" in text
    assert "HyperSmart-FinalV1-" in text
    assert "$FinalLabel = 'hypersmart-final-v1'" in text
    assert '--labels "$FinalLabel,alina"' in text
    assert "--runasservice" in text
    assert "--labels 'hypersmart,alina'" not in text
    assert "ancien label hypersmart" in text.casefold()


def test_final_installer_keeps_token_ephemeral_and_runtime_persistent() -> None:
    text = _text(INSTALLER)
    assert "registration-token" in text
    assert "Read-Host 'Token GitHub' -AsSecureString" in text
    assert "ZeroFreeBSTR" in text
    assert "$temporaryRunnerToken = $null" in text
    assert "ALINA_RESEARCH_HOME" in text
    assert "ALINA_PYTHON_EXE" in text
    assert "runtime\\python" in text
    assert "-m pip install --disable-pip-version-check -e $RepositoryRoot" in text
    assert "token.txt" not in text.casefold()


def test_final_installer_launcher_requires_explicit_go_and_waits_for_elevation() -> None:
    text = _text(INSTALLER_LAUNCHER)
    assert "GO_SELF_HOSTED" in text
    assert "INSTALLER_ALINA_RUNNER_FINAL_V1.ps1" in text
    assert "Start-Process" in text
    assert "-Verb RunAs" in text
    assert "-Wait -PassThru" in text
    assert "$p.ExitCode" in text


def test_final_control_document_exists_and_forbids_legacy_jobs() -> None:
    text = _text(CONTROL_README)
    assert "hypersmart-final-v1" in text
    assert "control/alina_final_jobs" in text
    assert "ancienne file" in text.casefold()
    assert "economic-3of3" in text
