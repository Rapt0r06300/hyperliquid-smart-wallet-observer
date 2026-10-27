from __future__ import annotations

import os
import shutil

import pytest
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAIN_LAUNCHER = ROOT / "POUSSER-GITHUB-FORCE.cmd"
ALIASES = [ROOT / "tools/launchers/POUSSER_TOUT_LE_TRAVAIL.cmd", ROOT / "tools/launchers/REPARER_ET_POUSSER.cmd"]
HELPER = ROOT / "tools" / "push_github_safe.ps1"
DRIVER = ROOT / "tools" / "alina_git_code_sync.py"


def _run(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _git(repo: Path, *args: str) -> str:
    return _run("git", *args, cwd=repo).stdout.strip()


def _helper_allowing_test_remote(tmp_path: Path, remote_url: str) -> Path:
    """Keep the production allowlist strict while exercising a local bare remote."""

    helper = tmp_path / "push_github_safe_test.ps1"
    original = '$command = @($driver, "--root", $ProjectRoot, "--git", $GitExecutable)'
    replacement = (
        '$command = @($driver, "--root", $ProjectRoot, "--git", '
        '$GitExecutable, "--test-remote")\n'
        '    $env:ALINA_SYNC_TEST_REMOTE_ALLOWED = "1"'
    )
    source = HELPER.read_text(encoding="utf-8")
    assert original in source
    source = source.replace(original, replacement, 1)
    helper.write_text(source, encoding="utf-8")
    return helper


def _include_sync_engine(repo: Path) -> None:
    tools = repo / "tools"
    tools.mkdir(exist_ok=True)
    shutil.copy2(DRIVER, tools / DRIVER.name)


def test_push_launchers_share_one_safe_implementation() -> None:
    main_text = MAIN_LAUNCHER.read_text(encoding="utf-8")
    helper_text = HELPER.read_text(encoding="utf-8")
    engine_text = DRIVER.read_text(encoding="utf-8")

    assert "tools\\alina_git_code_sync.py" in main_text
    assert "tools\\git\\cmd\\git.exe" in main_text
    assert '"%ALINA_ENGINE%" --root "%ALINA_ROOT%." --git "%HYPERSMART_GIT%" %SYNC_OPTION%' in main_text
    assert 'SYNC_OPTION=--dry-run' in main_text
    assert 'SYNC_OPTION=--wip-only' in main_text
    assert "GIT_SYNC_ENGINE_BUILD" in engine_text
    assert "FETCH_HEAD" not in engine_text
    assert '"push", "--progress", "origin", "HEAD:refs/heads/main"' in engine_text
    assert "merge-base" in engine_text
    assert '".bundle"' in engine_text
    assert '"reset", "--hard"' not in engine_text
    assert '"push", "--force"' not in engine_text
    assert '$driver = Join-Path $ProjectRoot "tools\\alina_git_code_sync.py"' in helper_text
    assert "Invoke-Git" not in helper_text
    assert '"runtime", "logs", "data", "datasets"' in engine_text

    for alias in ALIASES:
        alias_text = alias.read_text(encoding="utf-8")
        assert "POUSSER-GITHUB-FORCE.cmd" in alias_text
        assert "FETCH_HEAD" not in alias_text


def test_portable_git_installer_is_pinned_and_hash_verified() -> None:
    installer = (ROOT / "tools" / "install_portable_git.ps1").read_text(encoding="utf-8")
    bootstrap = (ROOT / "tools/launchers/PREPARER_GIT_PORTABLE.cmd").read_text(encoding="utf-8")

    assert "git-for-windows/git/releases/download" in installer
    assert "MinGit-2.54.0-64-bit.zip" in installer
    assert "04F937E1F0918B17B9BE6F2294CB2BB66E96E1D9832D1C298E2DE088A1D0E668" in installer
    assert "Get-FileHash" in installer
    assert "cmd\\git.exe" in installer
    assert 'cd /d "%~dp0"' in bootstrap
    assert "install_portable_git.ps1" in bootstrap


@pytest.mark.skipif(os.name != "nt", reason="le lanceur GitHub s'execute via Windows PowerShell")
def test_safe_push_reconciles_remote_and_keeps_bundles_out_of_main(tmp_path: Path) -> None:
    if shutil.which("powershell.exe") is None:
        raise AssertionError("Windows PowerShell est requis par le lanceur GitHub")

    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    local = tmp_path / "local"

    _run("git", "init", "--bare", str(remote), cwd=tmp_path)
    _run("git", "init", "-b", "main", str(seed), cwd=tmp_path)
    _git(seed, "config", "user.name", "HyperSmart Test")
    _git(seed, "config", "user.email", "hypersmart-test@example.invalid")
    _include_sync_engine(seed)
    (seed / "base.txt").write_text("base\n", encoding="utf-8")
    _git(seed, "add", "base.txt", "tools/alina_git_code_sync.py")
    _git(seed, "commit", "-m", "base")
    base_sha = _git(seed, "rev-parse", "HEAD")
    _git(seed, "branch", "a-pousser", base_sha)
    stale_bundle = tmp_path / "hypersmart_launcher.bundle"
    _git(seed, "bundle", "create", str(stale_bundle), "a-pousser")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")

    _run("git", "clone", "-b", "main", str(remote), str(local), cwd=tmp_path)
    _git(local, "config", "user.name", "HyperSmart Test")
    _git(local, "config", "user.email", "hypersmart-test@example.invalid")

    _git(seed, "checkout", "-b", "bundle-divergent", base_sha)
    (seed / "bundle-only.txt").write_text("bundle only\n", encoding="utf-8")
    _git(seed, "add", "bundle-only.txt")
    _git(seed, "commit", "-m", "divergent bundle work")
    divergent_sha = _git(seed, "rev-parse", "HEAD")
    divergent_bundle = tmp_path / "hypersmart_428.bundle"
    _git(seed, "bundle", "create", str(divergent_bundle), "bundle-divergent")
    _git(seed, "checkout", "main")

    (seed / "remote.txt").write_text("remote\n", encoding="utf-8")
    _git(seed, "add", "remote.txt")
    _git(seed, "commit", "-m", "remote work")
    remote_work_sha = _git(seed, "rev-parse", "HEAD")
    _git(seed, "push", "origin", "main")

    (local / "local.txt").write_text("local\n", encoding="utf-8")
    _git(local, "add", "local.txt")
    _git(local, "commit", "-m", "local work")
    local_work_sha = _git(local, "rev-parse", "HEAD")
    exclude_file = local / ".git" / "info" / "exclude"
    exclude_file.write_text("*.bundle\n", encoding="utf-8")
    shutil.copy2(stale_bundle, local / stale_bundle.name)
    shutil.copy2(divergent_bundle, local / divergent_bundle.name)
    test_helper = _helper_allowing_test_remote(
        tmp_path, _git(local, "remote", "get-url", "origin")
    )

    result = _run(
        "powershell.exe",
        "-NoLogo",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(test_helper),
        "-ProjectRoot",
        str(local),
        cwd=local,
    )

    assert "[INTEGRATION] Historiques divergents" in result.stdout
    assert "SHA local = SHA GitHub; synchronisation verifiee." in result.stdout
    remote_main = _git(local, "rev-parse", "refs/remotes/origin/main")
    assert _git(local, "rev-parse", "main") == remote_main
    assert _git(local, "merge-base", "--is-ancestor", remote_work_sha, remote_main) == ""
    assert _git(local, "merge-base", "--is-ancestor", local_work_sha, remote_main) == ""
    assert divergent_sha not in _git(local, "rev-list", "main").splitlines()
    assert (local / stale_bundle.name).is_file()
    assert (local / divergent_bundle.name).is_file()


@pytest.mark.skipif(os.name != "nt", reason="le helper GitHub s'execute via Windows PowerShell")
def test_safe_push_blocks_tracked_runtime_dirt_and_reports_source_dirt_in_dry_run(tmp_path: Path) -> None:
    git_exe = shutil.which("git")
    if git_exe is None or shutil.which("powershell.exe") is None:
        raise AssertionError("Git et Windows PowerShell sont requis")

    remote = tmp_path / "remote.git"
    seed = tmp_path / "seed"
    local = tmp_path / "local"
    _run("git", "init", "--bare", str(remote), cwd=tmp_path)
    _run("git", "init", "-b", "main", str(seed), cwd=tmp_path)
    _git(seed, "config", "user.name", "HyperSmart Test")
    _git(seed, "config", "user.email", "hypersmart-test@example.invalid")
    _include_sync_engine(seed)
    (seed / "runtime").mkdir()
    (seed / "src").mkdir()
    (seed / "runtime" / "state.json").write_text("{}\n", encoding="utf-8")
    (seed / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "base")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "main")
    _run("git", "clone", "-b", "main", str(remote), str(local), cwd=tmp_path)
    test_helper = _helper_allowing_test_remote(
        tmp_path, _git(local, "remote", "get-url", "origin")
    )

    (local / "runtime" / "state.json").write_text('{"live":true}\n', encoding="utf-8")
    local_head_before = _git(local, "rev-parse", "HEAD")
    remote_head_before = _git(local, "ls-remote", "origin", "refs/heads/main").split()[0]
    runtime_result = subprocess.run(
        (
            "powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(test_helper), "-ProjectRoot", str(local),
            "-GitExecutable", git_exe, "-DryRun",
        ),
        cwd=local,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert runtime_result.returncode == 2, runtime_result.stdout + runtime_result.stderr
    assert "Donnees Git suivies mais modifiees localement" in runtime_result.stdout
    assert (local / "runtime" / "state.json").read_text(encoding="utf-8") == '{"live":true}\n'
    assert _git(local, "rev-parse", "HEAD") == local_head_before
    assert _git(local, "ls-remote", "origin", "refs/heads/main").split()[0] == remote_head_before

    # Restore the fixture's tracked runtime file without invoking a destructive
    # Git operation, then verify that source edits are visible in dry-run mode.
    (local / "runtime" / "state.json").write_text("{}\n", encoding="utf-8")
    (local / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    source_result = subprocess.run(
        (
            "powershell.exe", "-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass",
            "-File", str(test_helper), "-ProjectRoot", str(local),
            "-GitExecutable", git_exe, "-DryRun",
        ),
        cwd=local,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert source_result.returncode == 0, source_result.stdout + source_result.stderr
    assert "[DRY-RUN] Aucun fichier prepare ou committe." in source_result.stdout
    assert "Aucun add, commit, fetch, merge ou push n'a ete execute." in source_result.stdout
    assert _git(local, "rev-parse", "HEAD") == local_head_before
    assert _git(local, "ls-remote", "origin", "refs/heads/main").split()[0] == remote_head_before
