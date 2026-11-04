"""Contrats statiques du launcher PowerShell officiel.

Ces tests ne démarrent ni moteur ni collecteur : ils verrouillent seulement les
preuves d'identité et de retour attendues avant toute opération Windows.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PS1 = (ROOT / "tools" / "start_hypersmart_simulation.ps1").read_text(
    encoding="utf-8", errors="strict"
)


def test_process_ownership_uses_a_directory_boundary():
    assert "$rootPrefix = $rootFull + [IO.Path]::DirectorySeparatorChar" in PS1
    assert "$executable.StartsWith($rootPrefix" in PS1
    assert "$executable.StartsWith($rootFull" not in PS1


def test_stop_is_graceful_then_force_bounded_and_checks_taskkill_exit_code():
    block = PS1.split("function Stop-HyperSmartProcessTree", 1)[1].split(
        "function Test-HyperSmartUiProcess", 1
    )[0]
    assert "Stop-Process -Id $ProcId -ErrorAction Stop" in block
    assert 'Start-Process -FilePath "taskkill.exe"' in block
    assert '"/PID", [string]$ProcId, "/T", "/F"' in block
    assert "$taskkill.ExitCode" in block
    assert "return $false" in block


def test_windows_paths_are_passed_as_working_directories_not_reparsed_commands():
    assert "-WorkingDirectory $Root" in PS1
    assert 'Join-Path $Root "runtime\\data"' in PS1
    assert 'Join-Path $Root "logs' in PS1


def test_startup_commands_capture_native_exit_codes_and_fail_closed():
    assert '$ErrorActionPreference = "Stop"' in PS1
    for command, variable in (
        ("init-db", "$initExitCode"),
        ("reset-simulation-state", "$resetExitCode"),
        ("prepare-simulation-logs", "$prepareExitCode"),
        ("discover-markets", "$marketsExitCode"),
        ("scan-markets", "$marketScanExitCode"),
    ):
        assert command in PS1
        assert f"if ({variable} -ne 0)" in PS1
    assert "$warmPublicScanExitCode = [int]$LASTEXITCODE" in PS1
    assert 'Stop-HyperSmartRuntime -Reason "startup_initialization_failed"' in PS1
    assert "exit 12" in PS1


def test_python_runtime_is_bound_to_the_portable_manifest_path():
    assert '$rootPrefixForPython = $rootFullForPython + [IO.Path]::DirectorySeparatorChar' in PS1
    assert '$PythonExe.StartsWith($rootPrefixForPython' in PS1
    assert '$expectedPythonExe = [IO.Path]::GetFullPath((Join-Path $Root "tools\\python\\python.exe"))' in PS1
    assert '$PythonExe, $expectedPythonExe' in PS1
    assert '$pythonManifestPath = Join-Path $Root "tools\\python\\portable_runtime_manifest.json"' in PS1
    assert '$manifestRuntimePath -ne "tools\\python\\python.exe"' in PS1


def test_launcher_keeps_ui_then_poller_order_and_fails_closed():
    ui_start = PS1.index('Write-LauncherLine "Demarrage du serveur UI local')
    poller_start = PS1.index('Write-LauncherLine "Demarrage du poller simulation read-only')
    readiness = PS1.index('$uiReady = Test-HyperSmartUiReady', poller_start)
    assert ui_start < poller_start < readiness
    assert 'Write-LauncherEngineStatus "ui_starting"' in PS1
    assert 'Write-LauncherEngineStatus "poller_starting"' in PS1
    assert 'Write-LauncherEngineStatus "ready"' in PS1
    for code, reason in ((13, "ui_start_failed"), (14, "poller_start_failed"), (15, "ui_readiness_failed"), (16, "ui_process_died"), (17, "poller_process_died"), (18, "ui_health_failed"), (19, "engine_safety_failed")):
        assert f"exit {code}" in PS1
        assert f'Stop-HyperSmartRuntime -Reason "{reason}"' in PS1
    assert "Test-HyperSmartUiReady" in PS1
    assert "Test-HyperSmartEngineReady" in PS1
    assert '$status.read_only -eq $true' in PS1
    assert '$status.simulation_only -eq $true' in PS1
    assert '$status.external_action -eq $false' in PS1


def test_stop_uses_the_requested_port_and_not_a_hardcoded_default():
    assert 'Get-NetTCPConnection -LocalPort $Port' in PS1
    assert 'Freeing verified HyperSmart UI port $Port' in PS1
    assert 'Get-NetTCPConnection -LocalPort 8794' not in PS1


def test_interactive_mode_monitors_children_and_handles_eof():
    assert "Get-HyperSmartStartedProcessFailures" in PS1
    assert "interactive child exit detected" in PS1
    assert "[Console]::IsInputRedirected" in PS1
    assert "interactive stdin EOF; exiting without prompt loop." in PS1
    assert 'Write-LauncherEngineStatus "child_exit"' in PS1


def test_pid_registry_orphan_audit_blocks_ready():
    assert 'hl_observer.ops.registre_pids enregistrer' in PS1
    assert '$registryPayload.audit.verdict -eq "ORPHAN"' in PS1
    assert 'Write-LauncherEngineStatus "orphan"' in PS1
    assert 'Stop-HyperSmartRuntime -Reason "pid_registry_orphan"' in PS1
    assert "exit 20" in PS1


def test_launcher_parameters_are_bounded_and_not_implicitly_reused():
    param_block = "\n".join(PS1.splitlines()[:15])
    assert '[ValidateRange(1, 65535)]' in param_block
    assert '[ValidateRange(1, 3600)]' in param_block
    assert '[ValidateRange(1, 10000)]' in param_block
    assert '$IntervalSeconds' in param_block
    assert '$MaxLeaders' in param_block
