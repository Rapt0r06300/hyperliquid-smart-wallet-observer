from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "alina-self-hosted.yml"
INSTALLER = ROOT / "tools" / "INSTALLER_ALINA_RUNNER_WINDOWS.ps1"
VERIFIER = ROOT / "tools" / "VERIFIER_ALINA_RUNNER_WINDOWS.ps1"
COCKPIT = ROOT / "tools" / "ALINA_RESEARCH_COCKPIT.ps1"
CONTROL_README = ROOT / "control" / "alina_jobs" / "README.md"
DOC = ROOT / "docs" / "ALINA_SELF_HOSTED_RUNNER.md"
LAUNCHER = ROOT / "LANCER_COCKPIT_ALINA.cmd"


def _text(path: Path) -> str:
    assert path.is_file(), f"Fichier obligatoire absent: {path}"
    return path.read_text(encoding="utf-8", errors="replace")


def test_workflow_cible_uniquement_le_runner_windows_hypersmart() -> None:
    text = _text(WORKFLOW)
    assert "runs-on: [self-hosted, Windows, X64, hypersmart]" in text
    assert "control/alina_jobs/*.json" in text
    assert "workflow_dispatch:" in text
    assert "pull_request:" not in text
    assert "cancel-in-progress: false" in text


def test_workflow_garde_des_permissions_minimales_et_ne_push_pas() -> None:
    text = _text(WORKFLOW)
    assert "permissions:\n  contents: read" in text
    assert "persist-credentials: false" in text
    assert "git push" not in text
    assert "contents: write" not in text
    assert "pull-requests: write" not in text


def test_workflow_force_paper_et_bloque_mainnet_testnet() -> None:
    text = _text(WORKFLOW)
    for needle in (
        "HL_ENABLE_MAINNET_EXECUTION: '0'",
        "HL_ENABLE_TESTNET_EXECUTION: '0'",
        "REAL_MAINNET_TRADING: 'false'",
        "HYPERSMART_ANALYSIS_LOCAL_ONLY: '1'",
        "hl_observer.ops.self_hosted_control",
        "hl_observer.ops.autonomous_research_guard",
    ):
        assert needle in text


def test_workflow_ne_remonte_que_le_result_dir_prepare_par_le_worker() -> None:
    text = _text(WORKFLOW)
    assert "actions/upload-artifact@v4" in text
    assert "path: ${{ steps.build.outputs.result_dir }}" in text
    assert "ALINA_RESEARCH_HOME" in text
    assert "gross_logs_stay_local = $true" in text
    assert "datasets\\assets" not in text.split("uses: actions/upload-artifact@v4", 1)[1]


def test_installateur_enregistre_un_service_et_ne_persiste_pas_le_token() -> None:
    text = _text(INSTALLER)
    for needle in (
        "--runasservice",
        "--labels 'hypersmart,alina'",
        "ALINA_RESEARCH_HOME",
        "actions/runners/registration-token",
        "Read-Host 'Token GitHub' -AsSecureString",
        "ZeroFreeBSTR",
        "$temporaryRunnerToken = $null",
    ):
        assert needle in text
    assert "Set-Content -Path" in text
    assert "RunnerToken | Set-Content" not in text
    assert "token.txt" not in text.casefold()


def test_verificateur_couvre_service_python_disque_et_cockpit() -> None:
    text = _text(VERIFIER)
    for needle in (
        "actions.runner.*",
        "Python 3.11+",
        "Réserve disque >= 25 Gio",
        "Cockpit copié",
        "DIAGNOSTIC FINAL : RUNNER PRÊT",
    ):
        assert needle in text


def test_tous_les_points_entree_publics_existent() -> None:
    for path in (WORKFLOW, INSTALLER, VERIFIER, COCKPIT, CONTROL_README, DOC, LAUNCHER):
        assert path.is_file(), str(path)
