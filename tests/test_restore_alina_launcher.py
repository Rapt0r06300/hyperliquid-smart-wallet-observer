"""Static launcher contract: a Windows fresh clone must support built-in recovery."""
from pathlib import Path


def test_restore_alina_cmd_selects_portable_then_python_and_keeps_fail_closed():
    script = (Path(__file__).resolve().parents[1] / "RESTORE_ALINA.cmd").read_text(
        encoding="utf-8"
    )
    assert 'if exist "%~dp0tools\\python\\python.exe" goto :embedded' in script
    assert "where py >nul 2>nul && goto :pylauncher" in script
    assert "where python >nul 2>nul && goto :system" in script
    assert script.count("tools\\restore_alina.py --everything") == 3
    assert script.count("--clone-root") == 3
    assert script.count("--destination") == 3
    assert script.count("exit /b %ERRORLEVEL%") == 3
    assert "git lfs pull" not in script.lower().replace("rem do not force git lfs pull", "")
    assert "stop" not in script.lower().replace("no collector is stopped", "")
