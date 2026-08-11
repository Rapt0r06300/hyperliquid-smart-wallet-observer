"""The master archive CMD delegates only to fail-closed portable orchestrators."""
from __future__ import annotations

import os
import subprocess

import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CMD = (ROOT / "CREER_ARCHIVE_PORTABLE.cmd").read_text(encoding="utf-8", errors="replace")


def test_embedded_python_is_the_only_runtime():
    assert 'call "%~dp0tools\\portable_env.cmd"' in CMD
    assert '"%HYPERSMART_PYTHON%" -m hl_observer.ops.archive_portable' in CMD
    assert '"%HYPERSMART_PYTHON%" -m hl_observer.ops.portable_release' in CMD
    assert "--mode-developpement" in CMD
    assert "--release-stricte" in CMD
    assert "where py" not in CMD and "py -3" not in CMD
    assert "portable_runtime\\python" not in CMD


def test_master_cmd_no_longer_mutates_or_checkpoints_source_session():
    assert "session_harvest" not in CMD
    assert "checkpoint" not in CMD.casefold()
    assert 'cd /d "%~dp0"' in CMD


def test_ok_can_only_be_printed_after_orchestrator_return_code():
    call = CMD.index("hl_observer.ops.archive_portable")
    result = CMD.index('set "RC=%ERRORLEVEL%"', call)
    success = CMD.index("[OK]", result)
    assert call < result < success
    assert 'if "%RC%"=="0"' in CMD[result:success]
    assert "reverifiee" in CMD[success:]


def test_paper_only_environment_is_explicit():
    assert 'set "HL_ENABLE_MAINNET_EXECUTION=0"' in CMD
    assert 'set "HL_ENABLE_TESTNET_EXECUTION=0"' in CMD
    assert 'set "TESTNET_EXECUTION_ENABLED=false"' in CMD
    assert 'set "REAL_MAINNET_TRADING=false"' in CMD


def test_sortie_dir_is_an_explicit_strict_release_contract():
    route = 'if /I "%~1"=="--sortie-dir" goto :release_output'
    assert route in CMD
    label = CMD.index("\n:release_output\n")
    strict_call = CMD.index("hl_observer.ops.portable_release", label)
    result = CMD.index('set "RC=%ERRORLEVEL%"', strict_call)
    block = CMD[label:result]
    assert 'if "%~2"==""' in block
    assert '--sortie-dir "%~2"' in block
    assert "hl_observer.ops.portable_clone" not in block
    assert "Dossier de sortie release manquant" in block


@pytest.mark.skipif(os.name != "nt", reason="execute le .cmd via cmd.exe (Windows uniquement)")
def test_unknown_argument_fails_without_success_banner():
    completed = subprocess.run(
        ["cmd.exe", "/d", "/c", str(ROOT / "CREER_ARCHIVE_PORTABLE.cmd"), "--unknown-option"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**__import__("os").environ, "CI": "true"}, check=False, timeout=60,
    )
    assert completed.returncode != 0
    assert "[REFUSE]" in completed.stdout
    assert "[OK] Archive conservee" not in completed.stdout
