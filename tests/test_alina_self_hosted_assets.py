from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "alina-self-hosted.yml"
INSTALLER = ROOT / "tools" / "INSTALLER_ALINA_RUNNER_WINDOWS.ps1"
VERIFIER = ROOT / "tools" / "VERIFIER_ALINA_RUNNER_WINDOWS.ps1"
COCKPIT = ROOT / "tools" / "ALINA_RESEARCH_COCKPIT.ps1"
CONTROL_README = ROOT / "control" / "alina_jobs" / "README.md"
DOC = ROOT / "docs" / "ALINA_SELF_HOSTED_RUNNER.md"
COCKPIT_LAUNCHER = ROOT / "LANCER_COCKPIT_ALINA.cmd"
INSTALLER_LAUNCHER = ROOT / "INSTALLER_ALINA_RUNNER_WINDOWS.cmd"
PREPARER = ROOT / "PREPARER_PC_ALINA.cmd"


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


def test_les_commandes_versionnees_sont_immuables() -> None:
    text = _text(WORKFLOW)
    assert "git diff-tree --no-commit-id --name-status" in text
    assert "COMMANDES_IMMUABLES" in text
    assert "$parts[0] -ne 'A'" in text
    assert "un job doit être un nouveau JSON ajouté" in text


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


def test_workflow_produit_un_retour_compact_avant_l_artifact() -> None:
    text = _text(WORKFLOW)
    assert "Construire le retour compact pour GitHub et ChatGPT" in text
    assert "hl_observer.ops.self_hosted_return" in text
    assert "ALINA_RETURN.json" in text
    assert "compact_return_ready" in text
    assert text.index("hl_observer.ops.self_hosted_return") < text.index("actions/upload-artifact@v4")


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


def test_installateur_configure_la_reprise_automatique_du_service() -> None:
    text = _text(INSTALLER)
    assert "Set-Service -Name $Service.Name -StartupType Automatic" in text
    assert "sc.exe failure $Service.Name" in text
    assert "restart/60000/restart/60000/restart/300000" in text
    assert "sc.exe failureflag $Service.Name 1" in text


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


def test_preparateur_local_est_non_destructeur_et_reste_sur_main() -> None:
    text = _text(PREPARER)
    assert 'git branch --show-current' in text
    assert 'not "%BRANCH%"=="main"' in text
    assert 'git status --porcelain' in text
    assert 'git pull --ff-only origin main' in text
    assert "VERIFIER_ALINA_RUNNER_WINDOWS.ps1" in text
    assert "LANCER_COCKPIT_ALINA.cmd" in text
    assert "[6/6] Ouverture du cockpit temps reel" in text
    lowered = text.casefold()
    assert 'git reset' not in lowered
    assert 'git clean' not in lowered
    assert 'checkout -f' not in lowered


def test_lanceur_installation_attend_reellement_l_elevation() -> None:
    text = _text(INSTALLER_LAUNCHER)
    assert "Start-Process" in text
    assert "-Verb RunAs" in text
    assert "-Wait -PassThru" in text
    assert "$p.ExitCode" in text
    assert "INSTALLER_ALINA_RUNNER_WINDOWS.ps1" in text


def test_cockpit_relit_la_variable_machine_si_la_fenetre_est_ancienne() -> None:
    text = _text(COCKPIT_LAUNCHER)
    assert "GetEnvironmentVariable('ALINA_RESEARCH_HOME','Machine')" in text
    assert "PREPARER_PC_ALINA.cmd" in text


def test_tous_les_points_entree_publics_existent() -> None:
    for path in (
        WORKFLOW,
        INSTALLER,
        VERIFIER,
        COCKPIT,
        CONTROL_README,
        DOC,
        COCKPIT_LAUNCHER,
        INSTALLER_LAUNCHER,
        PREPARER,
    ):
        assert path.is_file(), str(path)
