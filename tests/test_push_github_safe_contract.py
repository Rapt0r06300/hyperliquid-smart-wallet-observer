"""Safety contract for the active code-only Git reconciliation engine."""
from pathlib import Path

from tools.alina_git_code_sync import _protected

ROOT = Path(__file__).resolve().parents[1]


def test_local_shards_runtime_and_credentials_are_not_publishable() -> None:
    assert _protected("datasets/safe/shard.jsonl")
    assert _protected("runtime/reports/lab.json")
    assert _protected("logs/collector.log")
    assert _protected("config/.env")
    assert _protected("src/credentials/token.txt")
    assert not _protected("src/hl_observer/datasets/adapter.py")


def test_code_sync_is_main_only_and_never_rewrites_remote_history() -> None:
    source = (ROOT / "tools" / "alina_git_code_sync.py").read_text(encoding="utf-8")
    assert 'if self.text("branch", "--show-current") != "main":' in source
    assert '"push", "origin", "HEAD:refs/heads/main"' in source
    assert '"merge", "--no-edit", "--no-ff", remote' in source
    assert '"force_push": False' in source
    assert '"reset_or_clean": False' in source
    assert '"push", "--force"' not in source
    assert '"reset", "--hard"' not in source
    assert '"clean",' not in source
    assert '"stash",' not in source


def test_canonical_launcher_uses_python_engine_and_propagates_exit_code() -> None:
    launcher = (ROOT / "POUSSER-GITHUB-FORCE.cmd").read_text(encoding="utf-8-sig")
    assert 'set "ALINA_ENGINE=%ALINA_ROOT%tools\\alina_git_code_sync.py"' in launcher
    assert 'call :download_source "tools/alina_git_code_sync.py"' in launcher
    assert '"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% "%ALINA_ENGINE%" --root "%ALINA_ROOT%." --git "%HYPERSMART_GIT%" %SYNC_OPTION%' in launcher
    assert "endlocal & exit /b %RC%" in launcher
    assert "GIT_LFS_SKIP_SMUDGE=1" in launcher
    assert "tools\\push_github_safe.ps1" not in launcher
    assert "git push --force" not in launcher.lower()


def test_alias_buttons_invoke_single_canonical_launcher() -> None:
    for name in ("POUSSER_TOUT_LE_TRAVAIL.cmd", "REPARER_ET_POUSSER.cmd"):
        source = (ROOT / name).read_text(encoding="utf-8-sig")
        assert 'call "%~dp0POUSSER-GITHUB-FORCE.cmd"' in source
        assert "endlocal & exit /b %RC%" in source
