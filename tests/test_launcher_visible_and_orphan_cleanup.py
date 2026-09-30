from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_double_clic_garde_la_fenetre_ouverte_meme_apres_sortie_normale() -> None:
    launcher = (ROOT / "LANCER_HYPERSMART.cmd").read_text(
        encoding="utf-8", errors="replace"
    )

    assert 'set "HYPERSMART_INTERACTIVE_LAUNCH=0"' in launcher
    assert 'if "%~1"=="" set "HYPERSMART_INTERACTIVE_LAUNCH=1"' in launcher
    assert 'if "%HYPERSMART_INTERACTIVE_LAUNCH%"=="1" goto :fin_pause' in launcher
    assert "HyperSmart est arrete proprement. Cette fenetre reste ouverte." in launcher


def test_stop_et_restart_nettoient_uniquement_les_wrappers_du_projet() -> None:
    launcher = (ROOT / "LANCER_HYPERSMART.cmd").read_text(
        encoding="utf-8", errors="replace"
    )

    assert launcher.count("call :stop_launcher_wrappers") == 2
    assert "start_hypersmart_simulation.ps1" in launcher
    assert "Get-CimInstance Win32_Process" in launcher
    assert "-like ('*'+$root+'*')" in launcher
    assert "Start-Process -FilePath taskkill.exe" in launcher
    assert "'/PID',[string]$killPid,'/T','/F'" in launcher
    assert "$parent.CommandLine -like '*LANCER_HYPERSMART.cmd*'" in launcher
    assert 'taskkill /IM python.exe' not in launcher.lower()
    assert 'taskkill /IM powershell.exe' not in launcher.lower()


def test_demarrage_recupere_un_wrapper_orphelin_avant_le_runtime() -> None:
    script = (ROOT / "tools" / "start_hypersmart_simulation.ps1").read_text(
        encoding="utf-8", errors="replace"
    )

    assert "function Get-HyperSmartLauncherProcesses" in script
    assert "function Stop-HyperSmartLauncherTree" in script
    assert "$staleLaunchers = @(Get-HyperSmartLauncherProcesses)" in script
    assert "Arret ancien wrapper HyperSmart (arbre)" in script
    assert 'Join-Path $PSScriptRoot "start_hypersmart_simulation.ps1"' in script
    assert 'Stop-HyperSmartLauncherTree -LauncherProcess $launcherProcess' in script
