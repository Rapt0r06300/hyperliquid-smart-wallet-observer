"""Static launcher contract: a Windows fresh clone must support built-in recovery."""
from pathlib import Path


def test_restore_alina_cmd_selects_portable_then_python_and_keeps_fail_closed():
    script = (Path(__file__).resolve().parents[1] / "RESTORE_ALINA.cmd").read_text(
        encoding="utf-8"
    )
    assert 'if exist "%~dp0tools\\python\\python.exe" (' in script
    assert "where py >nul 2>nul && py -3 -c" in script
    assert "&& goto :pylauncher" in script
    assert "where python >nul 2>nul && python -c" in script
    assert "&& goto :system" in script
    assert script.count("sys.version_info[:2] < (3, 10)") == 3
    assert script.count("tools\\restore_alina.py --everything") == 3
    assert script.count("--clone-root") == 3
    assert script.count("--destination") == 3
    assert script.count("%*") == 3
    assert "gh auth token" in script
    assert "GH_TOKEN" in script and "GITHUB_TOKEN" in script
    assert script.count("exit /b %ERRORLEVEL%") == 3
    assert "git lfs pull" not in script.lower().replace("rem do not force git lfs pull", "")
    assert "stop" not in script.lower().replace("no collector is stopped", "")


def test_alina_restore_alias_preserves_arguments_and_exit_status():
    alias = (Path(__file__).resolve().parents[1] / "Alina-restore.cmd").read_text(
        encoding="utf-8"
    )
    assert 'call "%~dp0RESTORE_ALINA.cmd" %*' in alias
    assert "exit /b %ERRORLEVEL%" in alias
    assert "tools\\restore_alina.py" not in alias
