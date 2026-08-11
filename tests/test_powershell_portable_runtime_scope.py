from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "start_hypersmart_simulation.ps1"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8", errors="strict")


def test_powershell_uses_explicit_checkout_local_python_only():
    text = _text()
    assert '$PythonExe = [string]$env:HYPERSMART_PYTHON' in text
    assert 'Join-Path $Root "tools\\python\\python.exe"' in text
    assert 'Runtime Python refuse hors du checkout courant' in text
    assert '$env:HYPERSMART_PYTHON = $PythonExe' in text
    assert '& python ' not in text
    assert '-FilePath "python"' not in text


def test_poller_existing_detection_is_root_scoped():
    text = _text()
    start = text.index('$pollerAlreadyRunning = $false')
    end = text.index('if (-not $pollerAlreadyRunning)', start)
    block = text[start:end]
    assert 'Get-CimInstance Win32_Process' in block
    assert 'Test-HyperSmartProcessBelongsToRoot -Process $_' in block
    assert 'hypersmart_simulation_poll_loop.ps1' in block


def test_aux_existing_detection_is_root_scoped():
    text = _text()
    start = text.index('function Test-HyperSmartAuxRunning')
    end = text.index('if ($env:HYPERSMART_ENABLE_AUX_IA', start)
    block = text[start:end]
    assert 'Get-CimInstance Win32_Process' in block
    assert 'Test-HyperSmartProcessBelongsToRoot -Process $_' in block
    assert '$_.CommandLine -like $CommandPattern' in block


def test_ui_resource_policy_and_pid_registry_use_pinned_python():
    text = _text()
    assert 'Start-Process -WindowStyle Hidden -PassThru -FilePath $PythonExe' in text
    assert 'Start-Process -NoNewWindow -PassThru -FilePath $PythonExe' in text
    assert '& $PythonExe -m hl_observer.ops.registre_pids enregistrer "$Root"' in text


def test_script_has_no_stale_projectroot_alias():
    assert '$ProjectRoot' not in _text()
