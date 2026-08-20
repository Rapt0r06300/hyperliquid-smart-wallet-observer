from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREPARER = ROOT / "PREPARER_PC_ALINA.cmd"
INSTALLER_CMD = ROOT / "INSTALLER_ALINA_RUNNER_WINDOWS.cmd"
INSTALLER_PS1 = ROOT / "tools" / "INSTALLER_ALINA_RUNNER_WINDOWS.ps1"
COCKPIT = ROOT / "tools" / "ALINA_RESEARCH_COCKPIT.ps1"


def _text(path: Path) -> str:
    assert path.is_file(), path
    return path.read_text(encoding="utf-8", errors="replace")


def test_tous_les_points_d_installation_exigent_go_self_hosted_true() -> None:
    preparer = _text(PREPARER)
    installer_cmd = _text(INSTALLER_CMD)
    installer_ps1 = _text(INSTALLER_PS1)
    assert 'if /I not "%GO_SELF_HOSTED%"=="TRUE"' in preparer
    assert 'if /I not "%GO_SELF_HOSTED%"=="TRUE"' in installer_cmd
    assert "[string]$env:GO_SELF_HOSTED -cne 'TRUE'" in installer_ps1
    assert "GO_SELF_HOSTED=TRUE" in preparer
    assert "GO_SELF_HOSTED=TRUE" in installer_cmd
    assert "GO_SELF_HOSTED=TRUE" in installer_ps1
    assert "exit /b 9" in preparer
    assert "exit /b 9" in installer_cmd
    assert "exit 9" in installer_ps1


def test_le_verrou_go_arrive_avant_toute_installation_ou_elevation() -> None:
    preparer = _text(PREPARER)
    installer_cmd = _text(INSTALLER_CMD)
    installer_ps1 = _text(INSTALLER_PS1)
    assert preparer.index("GO_SELF_HOSTED") < preparer.index("git fetch origin main")
    assert installer_cmd.index("GO_SELF_HOSTED") < installer_cmd.index("Start-Process")
    assert installer_ps1.index("GO_SELF_HOSTED") < installer_ps1.index("Assert-Admin")
    assert installer_ps1.index("GO_SELF_HOSTED") < installer_ps1.index("Download-LatestRunner")


def test_cockpit_ne_confond_plus_service_local_et_connexion_github() -> None:
    text = _text(COCKPIT)
    assert "Service runner local" in text
    assert "Connexion GitHub prouvée" in text
    assert "GITHUB_SYNC_STATUS.json" in text
    assert "github_run_id" in text
    assert "github_sha" in text
    assert "heartbeat_unix" in text
    assert "service local != connexion GitHub" in text
    assert "Passerelle GitHub' 'EN LIGNE" not in text
