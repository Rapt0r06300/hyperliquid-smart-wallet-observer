from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "alina-self-hosted-final-v1.yml"
INSTALLER = ROOT / "tools" / "INSTALLER_ALINA_RUNNER_FINAL_V1.ps1"
INSTALLER_LAUNCHER = ROOT / "INSTALLER_ALINA_RUNNER_FINAL_V1.cmd"
CONTROLLER = ROOT / "tools" / "CONTROLER_ALINA_RUNNER_WINDOWS.ps1"
VERIFIER = ROOT / "tools" / "VERIFIER_ALINA_RUNNER_WINDOWS.ps1"
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


def test_final_workflow_public_gate_precedes_checkout_and_refuses_forks() -> None:
    text = _text(WORKFLOW)
    gate = text.index("Gate GitHub public avant checkout")
    checkout = text.index("Checkout exact du SHA sans credentials persistants")
    assert gate < checkout
    assert "github.event_name == 'push'" in text
    assert "github.actor == 'Rapt0r06300'" in text
    assert "github.event.repository.fork == false" in text
    assert "SELF_HOSTED_PUBLIC_FORK_REFUSED" in text
    assert "SELF_HOSTED_PUBLIC_SENDER_REFUSED" in text
    assert "SELF_HOSTED_PUBLIC_SHA_REFUSED" in text


def test_final_workflow_requires_exact_technical_green_before_compute() -> None:
    text = _text(WORKFLOW)
    assert "TECHNICAL_STATUS_NOT_GREEN" in text
    assert "TECHNICAL_STATUS_WAIT_TIMEOUT" in text
    assert "SELF_HOSTED_STALE_SHA_REFUSED_DURING_WAIT" in text
    assert "[DateTimeOffset]::UtcNow.AddMinutes(90)" in text
    assert "Start-Sleep -Seconds 30" in text
    assert "TECHNICAL_STATUS_WAIT" in text
    for context in (
        "hypersmart/pre-run-775",
        "hypersmart/technical-perfect",
        "hypersmart/security-quality",
    ):
        assert context in text
    gate = text.index("Attendre puis exiger les certifications techniques vertes du SHA exact")
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
    assert "[string]$RunnerRoot = 'C:\\actions-runner'" in text
    assert "'C:\\HyperSmart-Runner-Data'" in text
    assert "runner_workspace = (Join-Path $Root '_work')" in text
    assert "RUNNER_WORKSPACE_REFUSED" in text
    assert "RUNNER_DATA_ROOT_REFUSED" in text
    assert "HyperSmart-FinalV1-" in text
    assert "$FinalLabel = 'hypersmart-final-v1'" in text
    assert '--labels "$FinalLabel,alina"' in text
    assert "--runasservice" in text
    assert "--labels 'hypersmart,alina'" not in text
    assert "ancien label hypersmart" in text.casefold()
    assert "VERIFIER_ALINA_RUNNER_WINDOWS.ps1" in text
    assert "RUNNER_FINAL_NON_PRET" in text


def test_final_installer_verrouille_sha_main_et_mode_paper() -> None:
    text = _text(INSTALLER)
    assert "Get-ExactMainSha" in text
    assert "fetch origin main --quiet" in text
    assert "Le dépôt local doit être propre" in text
    assert "HEAD=$head origin/main=$remote" in text
    assert "HYPERSMART_RUNNER_PREPARED.json" in text
    assert "[switch]$PrepareOnly" in text
    assert "configured = $Configured" in text
    for marker in (
        "HL_ENABLE_MAINNET_EXECUTION = '0'",
        "HL_ENABLE_TESTNET_EXECUTION = '0'",
        "REAL_MAINNET_TRADING = 'false'",
        "TESTNET_EXECUTION_ENABLED = 'false'",
        "HYPERSMART_ANALYSIS_LOCAL_ONLY = '1'",
    ):
        assert marker in text


def test_controller_start_resume_are_fail_closed_and_emit_heartbeat() -> None:
    text = _text(CONTROLLER)
    assert "ValidateSet('Status', 'Start', 'Stop', 'Resume', 'Heartbeat', 'Diagnostic')" in text
    assert "RUNNER_NOT_REGISTERED" in text
    assert "RUNNER_WORKSPACE_REFUSED" in text
    assert "PREPARED_SHA_STALE" in text
    assert "PAPER_GUARD_REFUSED" in text
    assert "RUNNER_HEARTBEAT.json" in text
    assert "Start-Service" in text
    assert "Stop-Service" in text
    assert "real_execution = $false" in text


def test_verifier_targets_only_the_expected_runner_and_github_labels() -> None:
    text = _text(VERIFIER)
    assert "[string]$RunnerRoot = 'C:\\actions-runner'" in text
    assert "SHA exact de origin/main" in text
    assert "Workspace Actions séparé" in text
    assert "actions.runner.*" in text
    assert "PathName -match $prefix" in text
    assert "repos/Rapt0r06300/hyperliquid-smart-wallet-observer/actions/runners" in text
    for label in ("self-hosted", "Windows", "X64", "$RequiredLabel"):
        assert label in text
    assert "DIAGNOSTIC FINAL : RUNNER PRÊT" in text


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
    assert "-Elevate" in text
    assert text.count("-ConfirmSelfHosted") == 2


def test_final_installer_accepts_only_an_explicit_self_hosted_confirmation() -> None:
    text = _text(INSTALLER)
    assert "[switch]$ConfirmSelfHosted" in text
    assert "[switch]$Elevate" in text
    assert "[string]$env:GO_SELF_HOSTED -cne 'TRUE' -and -not $ConfirmSelfHosted" in text
    assert "Start-Process -FilePath 'powershell.exe' -Verb RunAs" in text
    assert "-Wait -PassThru -ErrorAction Stop" in text
    assert "exit $process.ExitCode" in text
    assert "exit 1223" in text


def test_final_control_document_exists_and_forbids_legacy_jobs() -> None:
    text = _text(CONTROL_README)
    assert "hypersmart-final-v1" in text
    assert "control/alina_final_jobs" in text
    assert "ancienne file" in text.casefold()
    assert "economic-3of3" in text
