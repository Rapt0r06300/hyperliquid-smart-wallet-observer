from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_double_click_launcher_uses_canonical_code_sync_engine() -> None:
    launcher = (ROOT / "POUSSER-GITHUB-FORCE.cmd").read_text(encoding="utf-8-sig")
    assert 'set "ALINA_ENGINE=%ALINA_ROOT%tools\\alina_git_code_sync.py"' in launcher
    assert 'call :download_source "tools/alina_git_code_sync.py"' in launcher
    assert 'if /I "%SYNC_OPTION%"=="--portable-self-check" goto :self_check' in launcher
    assert '"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% "%ALINA_ENGINE%" --root "%ALINA_ROOT%." --git "%HYPERSMART_GIT%" %SYNC_OPTION%' in launcher
    assert "GIT_LFS_SKIP_SMUDGE=1" in launcher
    assert "endlocal & exit /b %RC%" in launcher
    assert "tools\\push_github_safe.ps1" not in launcher


def test_alias_buttons_preserve_exit_status_from_canonical_launcher() -> None:
    for name in ("POUSSER_TOUT_LE_TRAVAIL.cmd", "REPARER_ET_POUSSER.cmd"):
        source = (ROOT / name).read_text(encoding="utf-8-sig")
        assert 'call "%~dp0POUSSER-GITHUB-FORCE.cmd"' in source
        assert 'set "RC=%ERRORLEVEL%"' in source
        assert "endlocal & exit /b %RC%" in source


def test_portable_git_installer_is_pinned_and_hash_verified() -> None:
    installer = (ROOT / "tools" / "install_portable_git.ps1").read_text(encoding="utf-8")
    bootstrap = (ROOT / "PREPARER_GIT_PORTABLE.cmd").read_text(encoding="utf-8")

    assert "git-for-windows/git/releases/download" in installer
    assert "MinGit-2.54.0-64-bit.zip" in installer
    assert "04F937E1F0918B17B9BE6F2294CB2BB66E96E1D9832D1C298E2DE088A1D0E668" in installer
    assert "Get-FileHash" in installer
    assert "cmd\\git.exe" in installer
    assert 'cd /d "%~dp0"' in bootstrap
    assert "install_portable_git.ps1" in bootstrap
